"""Fetch and merge station + price data from the Fuel Finder API."""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

from .api_client import FuelPricesAPI

_LOGGER = logging.getLogger(__name__)

# Map non-canonical fuel type strings returned by the API to their canonical forms.
_FUEL_TYPE_ALIASES: dict[str, str] = {
    "UNLEADED": "E10",
    "DIESEL": "B7",
    "SUPER_UNLEADED": "E5",
    "SUPER_DIESEL": "SDV",
    "PREMIUM_UNLEADED": "E5",
    "PREMIUM_DIESEL": "SDV",
}

# Prices above this threshold are assumed to be in pence and divided by 100.
_PENCE_THRESHOLD = 100.0


def _normalise_fuel_type(raw: str) -> str:
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    return _FUEL_TYPE_ALIASES.get(upper, upper)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres between two WGS-84 points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


async def fetch_stations_by_criteria(
    client: FuelPricesAPI,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 8.0,
    site_id: str | None = None,
    search_query: str | None = None,
    fuel_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return stations matching the given criteria, merged with current prices.

    Priority order:
      1. site_id — return the single matching station
      2. search_query — text filter on name / address / postcode
      3. lat + lon — all stations within radius_km
      4. No criteria — returns empty list

    Each result dict contains:
      site_id, name, address, postcode, latitude, longitude, brand,
      distance_km (None when no reference point), prices: {fuel_type: {price, last_updated}}
    """
    _LOGGER.debug(
        "fetch_stations_by_criteria lat=%s lon=%s radius=%s site_id=%s query=%r fuels=%s",
        latitude,
        longitude,
        radius_km,
        site_id,
        search_query,
        fuel_types,
    )

    if latitude is None and longitude is None and site_id is None and not search_query:
        _LOGGER.warning("fetch_stations_by_criteria called with no search criteria")
        return []

    _LOGGER.info("Fuel Prices UK: fetching station and price data from API…")
    try:
        stations_raw, prices_raw = await asyncio.gather(
            client.get_all_stations(),
            client.get_all_fuel_prices(),
        )
    except Exception:
        _LOGGER.error("Failed to fetch data from Fuel Finder API", exc_info=True)
        raise
    _LOGGER.info(
        "Fuel Prices UK: API returned %d station records and %d price records",
        len(stations_raw), len(prices_raw),
    )

    # Build price lookup: node_id/site_id → {canonical_fuel_type → {price, last_updated}}
    # The API returns records with a nested "fuel_prices" list; also handle legacy flat format.
    price_map: dict[str, dict[str, Any]] = {}
    skipped_no_sid = skipped_no_ft = skipped_no_price = 0
    for rec in prices_raw:
        sid = _str_field(rec, "node_id", "site_id", "siteId", "id")
        if not sid:
            skipped_no_sid += 1
            continue
        nested = rec.get("fuel_prices")
        if isinstance(nested, list):
            # New API format: fuel prices are a nested list within each station record
            for fp in nested:
                raw_ft = _str_field(fp, "fuel_type", "fuelType", "type")
                ft = _normalise_fuel_type(raw_ft) if raw_ft else ""
                if not ft:
                    skipped_no_ft += 1
                    continue
                raw_price = fp.get("price") or fp.get("price_in_pence")
                if raw_price is None:
                    skipped_no_price += 1
                    continue
                try:
                    price = float(raw_price)
                    if price > _PENCE_THRESHOLD:
                        price /= 100.0
                except (TypeError, ValueError):
                    skipped_no_price += 1
                    continue
                price_map.setdefault(sid, {})[ft] = {
                    "price": round(price, 3),
                    "last_updated": fp.get("price_last_updated")
                    or fp.get("last_updated")
                    or fp.get("lastUpdated"),
                }
        else:
            # Legacy flat format: one record per fuel type
            raw_ft = _str_field(rec, "fuel_type", "fuelType", "type")
            ft = _normalise_fuel_type(raw_ft) if raw_ft else ""
            if not ft:
                skipped_no_ft += 1
                continue
            raw_price = rec.get("price") or rec.get("price_in_pence")
            if raw_price is None:
                skipped_no_price += 1
                continue
            try:
                price = float(raw_price)
                if price > _PENCE_THRESHOLD:
                    price /= 100.0
            except (TypeError, ValueError):
                skipped_no_price += 1
                continue
            price_map.setdefault(sid, {})[ft] = {
                "price": round(price, 3),
                "last_updated": rec.get("last_updated")
                or rec.get("lastUpdated")
                or rec.get("updated_at"),
            }

    _LOGGER.info(
        "Fuel Prices UK: price map built — %d stations with prices, %d skipped "
        "(no_sid=%d, no_fuel_type=%d, no_price=%d)",
        len(price_map), skipped_no_sid + skipped_no_ft + skipped_no_price,
        skipped_no_sid, skipped_no_ft, skipped_no_price,
    )
    if prices_raw and not price_map:
        _LOGGER.warning(
            "Fuel Prices UK: price map is EMPTY despite %d raw price records — "
            "first record keys: %s, first record: %s",
            len(prices_raw), list(prices_raw[0].keys()), str(prices_raw[0])[:300],
        )

    if stations_raw:
        sample_station = stations_raw[0]
        _LOGGER.info(
            "Fuel Prices UK: station record keys: %s, sample: %s",
            list(sample_station.keys()), str(sample_station)[:300],
        )

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    n_no_sid = n_no_coords = n_outside_radius = n_no_price = 0

    for station in stations_raw:
        sid = _str_field(station, "node_id", "site_id", "siteId", "id")
        if not sid or sid in seen:
            n_no_sid += 1
            continue

        # Filter by site_id
        if site_id and sid != str(site_id):
            continue

        # Text search filter
        name = _str_field(station, "name", "trading_name", "station_name", "brand")
        addr = _str_field(station, "address", "street_address")
        postcode = _str_field(station, "postcode")
        if search_query:
            sq = search_query.lower()
            if not any(sq in f.lower() for f in (name, addr, postcode) if f):
                continue

        # Coordinates
        try:
            lat = float(station.get("latitude") or station.get("lat") or 0)
            lon = float(
                station.get("longitude")
                or station.get("lon")
                or station.get("long")
                or 0
            )
        except (TypeError, ValueError):
            lat = lon = 0.0

        # Radius filter — skip stations with no coordinates
        distance_km: float | None = None
        if latitude is not None and longitude is not None:
            if lat == 0.0 and lon == 0.0:
                n_no_coords += 1
                continue
            distance_km = _haversine_km(latitude, longitude, lat, lon)
            if distance_km > radius_km:
                n_outside_radius += 1
                continue

        prices = price_map.get(sid, {})

        # Fuel type filter — skip if none of the requested types have a price
        if fuel_types and not any(ft in prices for ft in fuel_types):
            n_no_price += 1
            continue

        results.append(
            {
                "site_id": sid,
                "name": name,
                "address": addr,
                "postcode": postcode,
                "latitude": lat,
                "longitude": lon,
                "brand": _str_field(station, "brand", "trading_name", "retailer"),
                "distance_km": round(distance_km, 3) if distance_km is not None else None,
                "prices": prices,
            }
        )
        seen.add(sid)

    _LOGGER.info(
        "Fuel Prices UK: station filter results — passed=%d, no_sid=%d, no_coords=%d, "
        "outside_radius=%d, no_matching_price=%d",
        len(results), n_no_sid, n_no_coords, n_outside_radius, n_no_price,
    )

    _LOGGER.debug("fetch_stations_by_criteria → %d stations after filtering", len(results))
    return results


def _str_field(obj: dict[str, Any], *keys: str) -> str:
    """Return the first non-empty string value found under any of the given keys."""
    for key in keys:
        val = obj.get(key)
        if val:
            return str(val)
    return ""
