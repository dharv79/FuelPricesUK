"""Fuel Prices UK — Home Assistant HACS integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import FuelPricesAPI
from .const import (
    CONF_CHEAPEST_COUNT,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DEVICE_TRACKER,
    CONF_FUELTYPES,
    CONF_LOCATION,
    CONF_LOCATION_METHOD,
    CONF_MAX_DATA_AGE_DAYS,
    CONF_NEAREST_COUNT,
    CONF_RADIUS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CHEAPEST_COUNT,
    DEFAULT_MAX_DATA_AGE_DAYS,
    DEFAULT_NEAREST_COUNT,
    DEFAULT_RADIUS_KM,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ENTRY_TITLE,
    FUEL_TYPE_B7,
    FUEL_TYPE_E10,
)
from .fetch_prices import fetch_stations_by_criteria

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fuel Prices UK from a config entry."""
    config = {**entry.data, **entry.options}

    client_id = str(config.get(CONF_CLIENT_ID, "")).strip()
    client_secret = str(config.get(CONF_CLIENT_SECRET, "")).strip()
    if not client_id or not client_secret:
        raise ConfigEntryNotReady(
            "Fuel Finder API credentials are missing — reconfigure the integration."
        )

    api_client = FuelPricesAPI(hass, client_id, client_secret)
    coordinator = FuelPricesDataUpdateCoordinator(
        hass,
        entry=entry,
        api_client=api_client,
        update_interval=timedelta(seconds=config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))

    # Stagger startup refreshes when multiple entries are configured.
    domain_data = hass.data[DOMAIN]
    domain_data["_counter"] = domain_data.get("_counter", 0) + 1
    stagger = (domain_data["_counter"] - 1) * 15
    coordinator.start_startup_refresh(delay_seconds=stagger)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(coordinator, FuelPricesDataUpdateCoordinator):
        coordinator.cancel_startup_refresh()

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return ok


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


# ------------------------------------------------------------------
# Coordinator
# ------------------------------------------------------------------


class FuelPricesDataUpdateCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Fetch fuel station data and keep sensors up to date."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api_client: FuelPricesAPI,
        update_interval: timedelta,
    ) -> None:
        self.entry = entry
        self.api_client = api_client
        self._startup_task: asyncio.Task[None] | None = None

        config = {**entry.data, **entry.options}
        self._location: dict[str, Any] = config.get(CONF_LOCATION) or {}
        self._radius_km: float = config.get(CONF_RADIUS, DEFAULT_RADIUS_KM)
        self._fuel_types: list[str] = config.get(CONF_FUELTYPES, [FUEL_TYPE_E10, FUEL_TYPE_B7])
        self._device_tracker: str | None = (
            config.get(CONF_DEVICE_TRACKER)
            if config.get(CONF_LOCATION_METHOD) == "device_tracker"
            else None
        )

        super().__init__(
            hass,
            _LOGGER,
            name=ENTRY_TITLE,
            config_entry=entry,
            update_interval=update_interval,
            always_update=False,
        )

    # ------------------------------------------------------------------
    # Startup refresh
    # ------------------------------------------------------------------

    def start_startup_refresh(self, delay_seconds: int = 0) -> None:
        if self._startup_task and not self._startup_task.done():
            return
        self._startup_task = self.hass.async_create_task(
            self._run_startup_refresh(delay_seconds),
            name=f"{DOMAIN}_{self.entry.entry_id}_startup",
        )

    def cancel_startup_refresh(self) -> None:
        if self._startup_task and not self._startup_task.done():
            self._startup_task.cancel()

    async def _run_startup_refresh(self, delay_seconds: int) -> None:
        if delay_seconds:
            try:
                await asyncio.sleep(delay_seconds)
            except asyncio.CancelledError:
                return
        try:
            await self.async_refresh()
            if not self.last_update_success:
                await asyncio.sleep(30)
                await self.async_refresh()
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.warning("Startup refresh failed; scheduled refresh will retry", exc_info=True)
        finally:
            self._startup_task = None

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> list[dict[str, Any]]:
        lat = self._location.get("latitude")
        lon = self._location.get("longitude")

        # Override with live device_tracker location if configured.
        if self._device_tracker:
            state = self.hass.states.get(self._device_tracker)
            if state and state.state not in ("unavailable", "unknown", "not_home"):
                try:
                    lat = float(state.attributes["latitude"])
                    lon = float(state.attributes["longitude"])
                except (KeyError, TypeError, ValueError):
                    _LOGGER.warning(
                        "device_tracker %s has no usable coordinates", self._device_tracker
                    )

        if lat is None or lon is None:
            _LOGGER.warning("No valid coordinates for coordinator %s", self.entry.entry_id)
            return []

        try:
            return await fetch_stations_by_criteria(
                self.api_client,
                latitude=lat,
                longitude=lon,
                radius_km=self._radius_km,
                fuel_types=self._fuel_types,
            )
        except Exception as exc:
            raise UpdateFailed(f"Error fetching fuel price data: {exc}") from exc
