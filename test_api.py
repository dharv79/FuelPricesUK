#!/usr/bin/env python3
"""Standalone diagnostic script for the UK Government Fuel Finder API.

Usage:
    python3 test_api.py <client_id> <client_secret> [postcode_or_coords]

Examples:
    python3 test_api.py MY_ID MY_SECRET
    python3 test_api.py MY_ID MY_SECRET "SW1A 1AA"
    python3 test_api.py MY_ID MY_SECRET "51.5074,-0.1278"

Requires: pip install aiohttp
"""
from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from typing import Any

try:
    import aiohttp
except ImportError:
    sys.exit("aiohttp not installed — run: pip install aiohttp")

API_BASE_URL = "https://www.fuel-finder.service.gov.uk"
API_TOKEN_PATH = "/api/v1/oauth/generate_access_token"
API_STATIONS_PATH = "/api/v1/pfs"
API_PRICES_PATH = "/api/v1/pfs/fuel-prices"

_FUEL_TYPE_ALIASES: dict[str, str] = {
    "UNLEADED": "E10", "DIESEL": "B7", "SUPER_UNLEADED": "E5",
    "SUPER_DIESEL": "SDV", "PREMIUM_UNLEADED": "E5", "PREMIUM_DIESEL": "SDV",
}


def _normalise_fuel_type(raw: str) -> str:
    upper = raw.upper().replace("-", "_").replace(" ", "_")
    return _FUEL_TYPE_ALIASES.get(upper, upper)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(min(1.0, a)))


def _extract_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "records", "results", "items", "stations", "prices"):
            if key in data and isinstance(data[key], list):
                return data[key]
        for value in data.values():
            found = _extract_records(value)
            if found:
                return found
    return []


async def get_token(session: aiohttp.ClientSession, client_id: str, client_secret: str) -> str:
    print(f"\n[1] Requesting OAuth token...")
    url = f"{API_BASE_URL}{API_TOKEN_PATH}"
    async with session.post(
        url,
        json={"client_id": client_id, "client_secret": client_secret},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=30),
    ) as resp:
        print(f"    Status: {resp.status}")
        if resp.status != 200:
            text = await resp.text()
            print(f"    ERROR: {text[:500]}")
            sys.exit(1)
        data = await resp.json()
        print(f"    Response keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        payload = data.get("data", data) if isinstance(data, dict) else data
        token = (payload.get("access_token") or payload.get("token")
                 or data.get("access_token") or data.get("token", ""))
        expires_in = int(payload.get("expires_in") or data.get("expires_in") or 3600)
        if not token:
            print(f"    ERROR: No token found in response: {json.dumps(data)[:300]}")
            sys.exit(1)
        print(f"    Token obtained (expires_in={expires_in}s): {token[:20]}...")
        return token


async def fetch_page(session: aiohttp.ClientSession, token: str, path: str, batch: int) -> tuple[int, Any]:
    url = f"{API_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with session.get(
        url, params={"batch-number": batch}, headers=headers,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        if resp.status == 404:
            return 404, None
        if resp.status != 200:
            text = await resp.text()
            return resp.status, text[:300]
        data = await resp.json()
        return resp.status, data


async def fetch_all(session: aiohttp.ClientSession, token: str, path: str, label: str) -> list[dict]:
    print(f"\n[{label}] Fetching all pages from {path}...")
    records: list[dict] = []
    batch = 1
    while True:
        t0 = time.time()
        status, data = await fetch_page(session, token, path, batch)
        elapsed = time.time() - t0
        if status == 404:
            print(f"    Batch {batch}: 404 (end of data) — done in {elapsed:.1f}s")
            break
        if status != 200:
            print(f"    Batch {batch}: HTTP {status} ERROR — {data}")
            break
        batch_records = _extract_records(data)
        print(f"    Batch {batch}: {status} OK, {len(batch_records)} records ({elapsed:.1f}s)")
        if not batch_records:
            print(f"    Batch {batch}: empty response — top-level keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
            if batch == 1:
                print(f"    First response sample: {json.dumps(data)[:500]}")
            break
        records.extend(batch_records)
        batch += 1
        await asyncio.sleep(0.2)
    return records


def parse_coords(arg: str) -> tuple[float, float] | None:
    try:
        parts = arg.split(",")
        if len(parts) == 2:
            return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        pass
    return None


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    client_id = sys.argv[1]
    client_secret = sys.argv[2]
    location_arg = sys.argv[3] if len(sys.argv) > 3 else None

    ref_lat: float | None = None
    ref_lon: float | None = None

    if location_arg:
        coords = parse_coords(location_arg)
        if coords:
            ref_lat, ref_lon = coords
        else:
            # Try geocoding via postcodes.io
            print(f"\n[0] Geocoding '{location_arg}'...")
            async with aiohttp.ClientSession() as tmp:
                normalised = location_arg.strip().upper().replace(" ", "")
                try:
                    async with tmp.get(
                        f"https://api.postcodes.io/postcodes/{normalised}",
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("status") == 200 and data.get("result"):
                                r = data["result"]
                                ref_lat = float(r["latitude"])
                                ref_lon = float(r["longitude"])
                                print(f"    Postcodes.io: ({ref_lat}, {ref_lon})")
                except Exception as e:
                    print(f"    Postcodes.io failed: {e}")

            if ref_lat is None:
                print(f"    Could not geocode '{location_arg}' — proceeding without radius filter")

    connector = aiohttp.TCPConnector(ssl=True)
    async with aiohttp.ClientSession(connector=connector) as session:
        token = await get_token(session, client_id, client_secret)

        t_start = time.time()
        stations, prices = await asyncio.gather(
            fetch_all(session, token, API_STATIONS_PATH, "2a STATIONS"),
            fetch_all(session, token, API_PRICES_PATH, "2b PRICES"),
        )
        t_total = time.time() - t_start

    print(f"\n[3] Summary")
    print(f"    Total fetch time: {t_total:.1f}s")
    print(f"    Stations: {len(stations)}")
    print(f"    Price records: {len(prices)}")

    if stations:
        print(f"\n    Station record sample (first):")
        print(f"    {json.dumps(stations[0], indent=6)}")

    if prices:
        print(f"\n    Price record sample (first):")
        print(f"    {json.dumps(prices[0], indent=6)}")

    # Build price map
    price_map: dict[str, dict[str, Any]] = {}
    for rec in prices:
        sid = (rec.get("site_id") or rec.get("siteId") or rec.get("id") or "")
        if not sid:
            continue
        raw_ft = rec.get("fuel_type") or rec.get("fuelType") or rec.get("type") or ""
        ft = _normalise_fuel_type(raw_ft) if raw_ft else ""
        if not ft:
            continue
        raw_price = rec.get("price") or rec.get("price_in_pence")
        if raw_price is None:
            continue
        try:
            price = float(raw_price)
            if price > 100.0:
                price /= 100.0
        except (TypeError, ValueError):
            continue
        price_map.setdefault(sid, {})[ft] = round(price, 3)

    fuel_counts: dict[str, int] = {}
    for fuels in price_map.values():
        for ft in fuels:
            fuel_counts[ft] = fuel_counts.get(ft, 0) + 1

    print(f"\n    Stations with prices: {len(price_map)}")
    print(f"    Price counts by fuel type: {dict(sorted(fuel_counts.items()))}")

    if ref_lat is not None and ref_lon is not None:
        print(f"\n[4] Stations within 8 km of ({ref_lat}, {ref_lon}):")
        nearby = []
        for s in stations:
            sid = str(s.get("site_id") or s.get("siteId") or s.get("id") or "")
            try:
                lat = float(s.get("latitude") or s.get("lat") or 0)
                lon = float(s.get("longitude") or s.get("lon") or s.get("long") or 0)
            except (TypeError, ValueError):
                continue
            if lat == 0.0 and lon == 0.0:
                continue
            dist = _haversine_km(ref_lat, ref_lon, lat, lon)
            if dist <= 8.0:
                nearby.append({
                    "site_id": sid,
                    "name": s.get("name") or s.get("station_name") or s.get("brand") or "",
                    "brand": s.get("brand") or s.get("retailer") or "",
                    "postcode": s.get("postcode") or "",
                    "distance_km": round(dist, 2),
                    "distance_miles": round(dist / 1.60934, 2),
                    "prices": price_map.get(sid, {}),
                })
        nearby.sort(key=lambda x: x["distance_km"])
        print(f"    Found {len(nearby)} stations")
        for s in nearby[:10]:
            p = s["prices"]
            price_str = ", ".join(f"{ft}={v:.3f}" for ft, v in sorted(p.items())) if p else "no prices"
            print(f"    {s['distance_miles']:.1f}mi  {s['name'] or s['brand']:30s}  {s['postcode']:10s}  {price_str}")
        if not nearby:
            print("    No stations found — try a larger radius or check your postcode")


asyncio.run(main())
