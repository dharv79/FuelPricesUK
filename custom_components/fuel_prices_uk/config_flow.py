"""Config flow for Fuel Prices UK integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .api_client import ApiHttpError, FuelPricesAPI
from .const import (
    CONF_ADDRESS,
    CONF_CHEAPEST_COUNT,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_FUELTYPES,
    CONF_LOCATION,
    CONF_LOCATION_METHOD,
    CONF_MAX_DATA_AGE_DAYS,
    CONF_NEAREST_COUNT,
    CONF_RADIUS,
    CONF_STATION_COUNT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CHEAPEST_COUNT,
    DEFAULT_MAX_DATA_AGE_DAYS,
    DEFAULT_NEAREST_COUNT,
    DEFAULT_RADIUS_KM,
    DEFAULT_STATION_COUNT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FUEL_TYPE_B7,
    FUEL_TYPE_E10,
    FUEL_TYPE_E5,
    FUEL_TYPE_SDV,
    FUEL_TYPES,
    KM_TO_MILES,
    LOCATION_METHOD_ADDRESS,
    LOCATION_METHOD_COORDINATES,
    LOCATION_METHOD_HOME,
    MAX_CHEAPEST_COUNT,
    MAX_NEAREST_COUNT,
    MAX_STATION_COUNT,
    MIN_CHEAPEST_COUNT,
    MILES_TO_KM,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_RADIUS_MILES = round(DEFAULT_RADIUS_KM * KM_TO_MILES, 1)


async def _geocode(hass: HomeAssistant, query: str) -> tuple[float, float] | None:
    """Resolve a UK postcode or place name to (latitude, longitude).

    Tries Postcodes.io first (fast, precise for UK postcodes), then falls
    back to the OpenStreetMap Nominatim geocoder.
    """
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=10)

    # --- Postcodes.io (UK postcodes only) ---
    normalised = query.strip().upper().replace(" ", "")
    try:
        async with session.get(
            f"https://api.postcodes.io/postcodes/{normalised}",
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("status") == 200 and data.get("result"):
                    r = data["result"]
                    return float(r["latitude"]), float(r["longitude"])
    except Exception:
        pass

    # --- Nominatim (addresses, town names, etc.) ---
    try:
        async with session.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{query}, United Kingdom", "format": "json", "limit": "1"},
            headers={"User-Agent": "FuelPricesUK-HomeAssistant/2026.05"},
            timeout=timeout,
        ) as resp:
            if resp.status == 200:
                results = await resp.json()
                if results:
                    return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass

    return None


class FuelPricesUKFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Multi-step config flow: credentials → location → options."""

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, str] = {}
        self._location: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1 — API credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            api = FuelPricesAPI(self.hass, client_id, client_secret)
            try:
                await api._get_token()
            except ApiHttpError as exc:
                errors["base"] = (
                    "invalid_auth" if exc.status in (401, 403) else "cannot_connect"
                )
            except Exception:
                _LOGGER.exception("Unexpected error validating API credentials")
                errors["base"] = "cannot_connect"
            else:
                self._credentials = {
                    CONF_CLIENT_ID: client_id,
                    CONF_CLIENT_SECRET: client_secret,
                }
                return await self.async_step_location()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 — Location
    # ------------------------------------------------------------------

    async def async_step_location(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            method = user_input[CONF_LOCATION_METHOD]

            if method == LOCATION_METHOD_HOME:
                lat = self.hass.config.latitude
                lon = self.hass.config.longitude
                if lat and lon:
                    self._location = {
                        "latitude": lat,
                        "longitude": lon,
                        "method": method,
                    }
                    return await self.async_step_options()
                errors["base"] = "home_location_not_set"

            elif method == LOCATION_METHOD_ADDRESS:
                query = (user_input.get(CONF_ADDRESS) or "").strip()
                if not query:
                    errors[CONF_ADDRESS] = "address_required"
                else:
                    coords = await _geocode(self.hass, query)
                    if coords:
                        self._location = {
                            "latitude": coords[0],
                            "longitude": coords[1],
                            "address": query,
                            "method": method,
                        }
                        return await self.async_step_options()
                    else:
                        errors["base"] = "geocode_failed"

            elif method == LOCATION_METHOD_COORDINATES:
                try:
                    lat = float(user_input.get(CONF_LATITUDE) or 0)
                    lon = float(user_input.get(CONF_LONGITUDE) or 0)
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        raise ValueError
                    self._location = {
                        "latitude": lat,
                        "longitude": lon,
                        "method": method,
                    }
                    return await self.async_step_options()
                except (TypeError, ValueError):
                    errors["base"] = "invalid_coordinates"

        return self.async_show_form(
            step_id="location",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCATION_METHOD, default=LOCATION_METHOD_ADDRESS
                    ): vol.In(
                        [
                            LOCATION_METHOD_HOME,
                            LOCATION_METHOD_ADDRESS,
                            LOCATION_METHOD_COORDINATES,
                        ]
                    ),
                    vol.Optional(CONF_ADDRESS): str,
                    vol.Optional(CONF_LATITUDE): vol.Coerce(float),
                    vol.Optional(CONF_LONGITUDE): vol.Coerce(float),
                }
            ),
            errors=errors,
            description_placeholders={
                "postcode_example": "e.g. SW1A 1AA or London",
            },
        )

    # ------------------------------------------------------------------
    # Step 3 — Options (radius, fuel types, intervals)
    # ------------------------------------------------------------------

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            fuel_types = _selected_fuel_types(user_input)
            if not fuel_types:
                errors["base"] = "no_fuel_types"
            else:
                radius_km = round(
                    float(user_input["radius_miles"]) * MILES_TO_KM, 3
                )
                label = self._location.get("address") or (
                    f"{self._location['latitude']:.4f}, {self._location['longitude']:.4f}"
                )
                return self.async_create_entry(
                    title=f"Fuel Prices UK — {label}",
                    data={
                        **self._credentials,
                        CONF_LOCATION: self._location,
                        CONF_LOCATION_METHOD: self._location["method"],
                        CONF_RADIUS: radius_km,
                        CONF_FUELTYPES: fuel_types,
                        CONF_UPDATE_INTERVAL: int(
                            user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
                        ),
                        CONF_CHEAPEST_COUNT: int(
                            user_input.get(CONF_CHEAPEST_COUNT, DEFAULT_CHEAPEST_COUNT)
                        ),
                        CONF_NEAREST_COUNT: int(
                            user_input.get(CONF_NEAREST_COUNT, DEFAULT_NEAREST_COUNT)
                        ),
                        CONF_STATION_COUNT: int(
                            user_input.get(CONF_STATION_COUNT, DEFAULT_STATION_COUNT)
                        ),
                        CONF_MAX_DATA_AGE_DAYS: int(
                            user_input.get(CONF_MAX_DATA_AGE_DAYS, DEFAULT_MAX_DATA_AGE_DAYS)
                        ),
                    },
                )

        return self.async_show_form(
            step_id="options",
            data_schema=_options_schema(),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Options flow (re-configure existing entry)
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Allow reconfiguring an existing Fuel Prices UK entry."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        current = {**self._entry.data, **self._entry.options}

        if user_input is not None:
            fuel_types = _selected_fuel_types(user_input)
            if not fuel_types:
                errors["base"] = "no_fuel_types"
            else:
                radius_km = round(
                    float(user_input["radius_miles"]) * MILES_TO_KM, 3
                )
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_RADIUS: radius_km,
                        CONF_FUELTYPES: fuel_types,
                        CONF_UPDATE_INTERVAL: int(
                            user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
                        ),
                        CONF_CHEAPEST_COUNT: int(
                            user_input.get(CONF_CHEAPEST_COUNT, DEFAULT_CHEAPEST_COUNT)
                        ),
                        CONF_NEAREST_COUNT: int(
                            user_input.get(CONF_NEAREST_COUNT, DEFAULT_NEAREST_COUNT)
                        ),
                        CONF_STATION_COUNT: int(
                            user_input.get(CONF_STATION_COUNT, DEFAULT_STATION_COUNT)
                        ),
                        CONF_MAX_DATA_AGE_DAYS: int(
                            user_input.get(
                                CONF_MAX_DATA_AGE_DAYS, DEFAULT_MAX_DATA_AGE_DAYS
                            )
                        ),
                    },
                )

        current_radius_miles = round(
            current.get(CONF_RADIUS, DEFAULT_RADIUS_KM) * KM_TO_MILES, 1
        )
        current_fuels: list[str] = current.get(
            CONF_FUELTYPES, [FUEL_TYPE_E10, FUEL_TYPE_B7]
        )

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(
                radius_miles=current_radius_miles,
                fuels=current_fuels,
                cheapest=current.get(CONF_CHEAPEST_COUNT, DEFAULT_CHEAPEST_COUNT),
                nearest=current.get(CONF_NEAREST_COUNT, DEFAULT_NEAREST_COUNT),
                station_count=current.get(CONF_STATION_COUNT, DEFAULT_STATION_COUNT),
                interval=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                age_days=current.get(CONF_MAX_DATA_AGE_DAYS, DEFAULT_MAX_DATA_AGE_DAYS),
            ),
            errors=errors,
        )


# ------------------------------------------------------------------
# Schema helpers
# ------------------------------------------------------------------


def _options_schema(
    radius_miles: float = _DEFAULT_RADIUS_MILES,
    fuels: list[str] | None = None,
    cheapest: int = DEFAULT_CHEAPEST_COUNT,
    nearest: int = DEFAULT_NEAREST_COUNT,
    station_count: int = DEFAULT_STATION_COUNT,
    interval: int = DEFAULT_UPDATE_INTERVAL,
    age_days: int = DEFAULT_MAX_DATA_AGE_DAYS,
) -> vol.Schema:
    if fuels is None:
        fuels = [FUEL_TYPE_E10, FUEL_TYPE_B7]
    return vol.Schema(
        {
            vol.Optional("radius_miles", default=radius_miles): vol.All(
                vol.Coerce(float), vol.Range(min=0.5, max=31)
            ),
            vol.Optional(
                f"fuel_{FUEL_TYPE_E10.lower()}", default=FUEL_TYPE_E10 in fuels
            ): bool,
            vol.Optional(
                f"fuel_{FUEL_TYPE_E5.lower()}", default=FUEL_TYPE_E5 in fuels
            ): bool,
            vol.Optional(
                f"fuel_{FUEL_TYPE_B7.lower()}", default=FUEL_TYPE_B7 in fuels
            ): bool,
            vol.Optional(
                f"fuel_{FUEL_TYPE_SDV.lower()}", default=FUEL_TYPE_SDV in fuels
            ): bool,
            vol.Optional(CONF_CHEAPEST_COUNT, default=cheapest): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_CHEAPEST_COUNT, max=MAX_CHEAPEST_COUNT)
            ),
            vol.Optional(CONF_NEAREST_COUNT, default=nearest): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_NEAREST_COUNT)
            ),
            vol.Optional(CONF_STATION_COUNT, default=station_count): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_STATION_COUNT)
            ),
            vol.Optional(CONF_UPDATE_INTERVAL, default=interval): vol.All(
                vol.Coerce(int), vol.Range(min=300, max=86400)
            ),
            vol.Optional(CONF_MAX_DATA_AGE_DAYS, default=age_days): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=30)
            ),
        }
    )


def _selected_fuel_types(user_input: dict[str, Any]) -> list[str]:
    """Extract the list of selected fuel types from options form data."""
    return [ft for ft in FUEL_TYPES if user_input.get(f"fuel_{ft.lower()}", False)]
