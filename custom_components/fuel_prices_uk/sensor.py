"""Sensor platform for Fuel Prices UK."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FuelPricesDataUpdateCoordinator
from .const import (
    CONF_CHEAPEST_COUNT,
    CONF_FUELTYPES,
    CONF_MAX_DATA_AGE_DAYS,
    CONF_NEAREST_COUNT,
    DEFAULT_CHEAPEST_COUNT,
    DEFAULT_MAX_DATA_AGE_DAYS,
    DEFAULT_NEAREST_COUNT,
    DOMAIN,
    FUEL_LABELS,
    FUEL_TYPE_B7,
    FUEL_TYPE_E10,
    KM_TO_MILES,
)

_LOGGER = logging.getLogger(__name__)

_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}
_ATTRIBUTION = "Data provided by UK Government Fuel Price open data scheme"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FuelPricesDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    config = {**entry.data, **entry.options}

    fuel_types: list[str] = config.get(CONF_FUELTYPES, [FUEL_TYPE_E10, FUEL_TYPE_B7])
    cheapest_count: int = config.get(CONF_CHEAPEST_COUNT, DEFAULT_CHEAPEST_COUNT)
    nearest_count: int = config.get(CONF_NEAREST_COUNT, DEFAULT_NEAREST_COUNT)
    max_age_days: int = config.get(CONF_MAX_DATA_AGE_DAYS, DEFAULT_MAX_DATA_AGE_DAYS)

    entities: list[SensorEntity] = []
    for fuel_type in fuel_types:
        for rank in range(1, cheapest_count + 1):
            entities.append(
                CheapestFuelPriceSensor(coordinator, entry, fuel_type, rank, max_age_days)
            )
        for rank in range(1, nearest_count + 1):
            entities.append(
                NearestFuelStationSensor(coordinator, entry, fuel_type, rank, max_age_days)
            )

    async_add_entities(entities)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _filter_and_price(
    stations: list[dict[str, Any]],
    fuel_type: str,
    max_age_days: int,
) -> list[dict[str, Any]]:
    """Return stations that have a valid, non-stale price for fuel_type."""
    cutoff: datetime | None = None
    if max_age_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    result = []
    for station in stations:
        price_info = station.get("prices", {}).get(fuel_type)
        if price_info is None:
            continue
        price = price_info.get("price")
        if price is None:
            continue
        if cutoff and price_info.get("last_updated"):
            try:
                updated = datetime.fromisoformat(
                    str(price_info["last_updated"]).replace("Z", "+00:00")
                )
                if updated < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        result.append({**station, "_price": float(price), "_fuel_type": fuel_type})
    if not result and stations:
        _LOGGER.warning(
            "Fuel Prices UK: no %s prices passed sensor filter "
            "(checked %d stations, cutoff=%s) — "
            "try increasing max_data_age_days in Options",
            fuel_type, len(stations), cutoff,
        )
    return result


def _ordinal(n: int) -> str:
    return _ORDINALS.get(n, f"{n}th")


# ------------------------------------------------------------------
# Sensor classes
# ------------------------------------------------------------------


class CheapestFuelPriceSensor(CoordinatorEntity, SensorEntity):
    """Nth cheapest fuel station for a given fuel type."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "GBP/L"
    _attr_attribution = _ATTRIBUTION
    _attr_icon = "mdi:gas-station"

    def __init__(
        self,
        coordinator: FuelPricesDataUpdateCoordinator,
        entry: ConfigEntry,
        fuel_type: str,
        rank: int,
        max_age_days: int,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._fuel_type = fuel_type
        self._rank = rank
        self._max_age_days = max_age_days
        self._attr_unique_id = f"{entry.entry_id}_{fuel_type}_cheapest_{rank}"
        label = "Cheapest" if rank == 1 else f"{_ordinal(rank)} Cheapest"
        self._attr_name = (
            f"Fuel Prices UK — {label} {FUEL_LABELS.get(fuel_type, fuel_type)}"
        )

    def _ranked_station(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        stations = _filter_and_price(
            self.coordinator.data, self._fuel_type, self._max_age_days
        )
        stations.sort(key=lambda s: (s["_price"], s.get("site_id", "")))
        idx = self._rank - 1
        return stations[idx] if idx < len(stations) else None

    @property
    def native_value(self) -> float | None:
        s = self._ranked_station()
        return s["_price"] if s else None

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._ranked_station() is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._ranked_station()
        if not s:
            return {}
        price_info = s.get("prices", {}).get(self._fuel_type, {})
        dist_km = s.get("distance_km")
        return {
            "fuel_type": self._fuel_type,
            "fuel_type_label": FUEL_LABELS.get(self._fuel_type, self._fuel_type),
            "price_rank": self._rank,
            "price_rank_label": f"{_ordinal(self._rank)} cheapest",
            "station_name": s.get("name"),
            "brand": s.get("brand"),
            "address": s.get("address"),
            "postcode": s.get("postcode"),
            "latitude": s.get("latitude"),
            "longitude": s.get("longitude"),
            "distance_km": dist_km,
            "distance_miles": (
                round(dist_km * KM_TO_MILES, 2) if dist_km is not None else None
            ),
            "site_id": s.get("site_id"),
            "last_updated": price_info.get("last_updated"),
        }


class NearestFuelStationSensor(CheapestFuelPriceSensor):
    """Nth nearest station (sorted by distance, not price)."""

    def __init__(
        self,
        coordinator: FuelPricesDataUpdateCoordinator,
        entry: ConfigEntry,
        fuel_type: str,
        rank: int,
        max_age_days: int,
    ) -> None:
        super().__init__(coordinator, entry, fuel_type, rank, max_age_days)
        self._attr_unique_id = f"{entry.entry_id}_{fuel_type}_nearest_{rank}"
        self._attr_name = (
            f"Fuel Prices UK — {_ordinal(rank)} Nearest "
            f"{FUEL_LABELS.get(fuel_type, fuel_type)}"
        )

    def _ranked_station(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        stations = _filter_and_price(
            self.coordinator.data, self._fuel_type, self._max_age_days
        )
        stations = [s for s in stations if s.get("distance_km") is not None]
        stations.sort(key=lambda s: (s["distance_km"], s.get("site_id", "")))
        idx = self._rank - 1
        return stations[idx] if idx < len(stations) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if attrs:
            attrs["distance_rank"] = self._rank
            attrs["distance_rank_label"] = f"{_ordinal(self._rank)} nearest"
        return attrs
