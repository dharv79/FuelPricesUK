# Fuel Prices UK — CLAUDE.md

## Project overview

A Home Assistant custom component (HACS integration) that surfaces live UK petrol-station fuel prices as HA sensors. Data is sourced from the **UK Government Fuel Finder** public API.

- **API portal**: https://www.developer.fuel-finder.service.gov.uk/public-api
- **Data scheme**: https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email
- **HACS compatible**: yes (`hacs.json` in repo root, component under `custom_components/fuel_prices_uk/`)
- **Minimum HA version**: 2024.6.0

---

## Repository layout

```
FuelPricesUK/
├── CLAUDE.md                                   ← this file
├── hacs.json                                   ← HACS metadata
├── README.md
└── custom_components/
    └── fuel_prices_uk/
        ├── __init__.py          ← integration setup + DataUpdateCoordinator
        ├── api_client.py        ← OAuth2 + REST client for the Fuel Finder API
        ├── config_flow.py       ← UI setup wizard (credentials → location → options)
        ├── const.py             ← all shared constants
        ├── fetch_prices.py      ← merges station + price data, radius/text filter
        ├── manifest.json        ← HA integration manifest
        ├── sensor.py            ← sensor platform (cheapest + nearest entities)
        ├── strings.json         ← UI strings referenced by config flow
        └── translations/
            └── en.json          ← English translations (copy of strings.json)
```

---

## API details

### Authentication

OAuth 2.0 **client credentials** flow. Credentials are issued via the developer portal.

```
POST https://api.fuel-finder.service.gov.uk/api/v1/oauth/generate_access_token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<ID>&client_secret=<SECRET>
```

Response:
```json
{ "access_token": "...", "expires_in": 3600, "token_type": "Bearer" }
```

Use `Authorization: Bearer <token>` on all subsequent requests.

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/pfs` | Station metadata (name, address, postcode, lat/lon, brand) |
| `GET` | `/api/v1/pfs/fuel-prices` | Current fuel prices per station |

Both endpoints support `?page=N&pageSize=500` pagination. The client pages until a batch smaller than `pageSize` is returned.

### Fuel types

| Code | Description |
|------|-------------|
| `E10` | Standard unleaded petrol |
| `E5` | Super unleaded / premium petrol |
| `B7` | Standard diesel |
| `SDV` | Super diesel / premium diesel |

Prices are returned in **pence per litre**; the client converts values >100 to £/L automatically.

---

## Architecture

```
config_flow.py          user enters credentials + location
       │
       ▼
__init__.py             creates FuelPricesDataUpdateCoordinator
       │
       ▼
fetch_prices.py         calls api_client.get_all_stations() +
                        get_all_fuel_prices() concurrently,
                        merges, filters by radius / fuel type
       │
       ▼
sensor.py               reads coordinator.data to expose
                        CheapestFuelPriceSensor + NearestFuelStationSensor
```

### Coordinator (`FuelPricesDataUpdateCoordinator`)

- Lives in `__init__.py`, extends `DataUpdateCoordinator[list[dict]]`.
- On startup, fires a background refresh (staggered by 15 s per entry to avoid API bursts).
- Retries once after 30 s if the first refresh fails.
- Supports `device_tracker` entity as a dynamic location source.

### API client (`FuelPricesAPI`)

- Manages a shared token cache keyed by `(client_id, client_secret)` — multiple config entries sharing the same credentials reuse one token.
- Handles 429 rate-limit responses with `Retry-After` back-off and retries up to 4 times.
- Pages through all records automatically via `get_all_stations()` / `get_all_fuel_prices()`.

### Location resolution (`config_flow._geocode`)

1. **Postcodes.io** — tried first for anything that looks like a UK postcode (fast, authoritative).
2. **Nominatim (OpenStreetMap)** — fallback for town names, addresses, etc.

---

## Sensors produced

For each configured fuel type, the integration creates:

- **Cheapest** sensors (1–5): `sensor.fuel_prices_uk_<location>_cheapest_<fuel>`, `…_2nd_cheapest_<fuel>`, …
- **Nearest** sensors (0–5): `sensor.fuel_prices_uk_<location>_1st_nearest_<fuel>`, …

State = price in **£/L** (3 decimal places). Attributes include:

| Attribute | Description |
|-----------|-------------|
| `fuel_type` | `E10`, `E5`, `B7`, or `SDV` |
| `station_name` | Forecourt name |
| `brand` | e.g. `BP`, `Shell`, `Tesco` |
| `address` | Street address |
| `postcode` | Station postcode |
| `latitude` / `longitude` | Station coordinates |
| `distance_km` / `distance_miles` | Distance from search point |
| `price_rank` / `distance_rank` | Rank (1 = cheapest / nearest) |
| `last_updated` | ISO-8601 timestamp from the API |

---

## Configuration options

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| `client_id` | — | — | API Client ID |
| `client_secret` | — | — | API Client Secret |
| Location method | `address` | home / address / coordinates | How to set the search centre |
| Postcode / address | — | — | UK postcode or place name |
| `radius_miles` | 5 | 0.5–31 | Search radius |
| Fuel types | E10, B7 | multi | Which fuel types to track |
| `cheapest_count` | 3 | 1–5 | How many cheapest sensors per fuel type |
| `nearest_count` | 0 | 0–5 | How many nearest sensors per fuel type |
| `update_interval` | 3600 | 300–86400 | Refresh interval in seconds |
| `max_data_age_days` | 1 | 0–30 | Drop stale price records (0 = keep all) |

---

## Installation (HACS)

1. In HACS → Integrations → click the three-dot menu → **Custom repositories**.
2. Add `https://github.com/dharv79/fuelpricesuk` with category **Integration**.
3. Click **Download**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration** → search **Fuel Prices UK**.

### Manual installation

Copy `custom_components/fuel_prices_uk/` into your HA `config/custom_components/` directory, then restart.

---

## Development

### Running tests / linting

```bash
pip install homeassistant pytest pytest-homeassistant-custom-component
pytest tests/
```

### Key design decisions

- **No geopy dependency** — geocoding uses `postcodes.io` (postcodes) and Nominatim (addresses) via `aiohttp`, which is already a core HA dependency. This avoids extra wheel installs.
- **Shared token cache** — `_TOKEN_CACHE` in `api_client.py` is a module-level dict keyed by credential pair so concurrent config entries don't double-request tokens.
- **Haversine distance** — implemented in `fetch_prices._haversine_km` to avoid the geopy dependency for distance calculations.
- **Price unit normalisation** — prices above 100 are assumed to be in pence and divided by 100.0.
- **`always_update=False`** on the coordinator — prevents unnecessary HA state writes when data hasn't changed.

---

## Useful links

- [UK Government Fuel Finder developer portal](https://www.developer.fuel-finder.service.gov.uk)
- [GOV.UK guidance — access fuel price data](https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email)
- [Home Assistant custom component docs](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [HACS documentation](https://hacs.xyz/docs/publish/integration)
