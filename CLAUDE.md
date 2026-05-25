# Fuel Prices UK — CLAUDE.md

## Project overview

A Home Assistant custom component (HACS integration) that surfaces live UK petrol-station fuel prices as HA sensors, sourced from the **UK Government Fuel Finder** open data scheme.

- **API developer portal**: https://www.developer.fuel-finder.service.gov.uk/public-api
- **GOV.UK guidance**: https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email
- **HACS compatible**: yes — `hacs.json` in repo root, component under `custom_components/fuel_prices_uk/`
- **Minimum HA version**: 2024.6.0
- **Current version**: 2.0.0
- **Licence**: Apache 2.0

---

## Repository layout

```
FuelPricesUK/
├── CLAUDE.md                                        ← this file
├── README.md                                        ← user-facing docs (rendered by HACS)
├── hacs.json                                        ← HACS metadata
├── .github/
│   └── workflows/
│       └── release.yml                              ← manual trigger workflow to tag + publish release
└── custom_components/
    └── fuel_prices_uk/
        ├── __init__.py          ← integration setup + DataUpdateCoordinator
        ├── api_client.py        ← OAuth2 token management + paginated REST client
        ├── config_flow.py       ← 3-step UI wizard: credentials → location → options
        ├── const.py             ← all shared constants and defaults
        ├── fetch_prices.py      ← merges station + price data; radius/text filter
        ├── manifest.json        ← HA integration manifest (domain, version, requirements)
        ├── sensor.py            ← CheapestFuelPriceSensor + NearestFuelStationSensor + StationSensor
        ├── strings.json         ← config flow UI strings (referenced by HA frontend)
        └── translations/
            └── en.json          ← English translations (mirrors strings.json)
```

---

## API

### Authentication

OAuth 2.0 **client credentials** flow. Credentials are issued free via the developer portal.

```
POST https://api.fuel-finder.service.gov.uk/api/v1/oauth/generate_access_token
Content-Type: application/json

{"client_id": "<ID>", "client_secret": "<SECRET>"}
```

Response:
```json
{ "access_token": "...", "expires_in": 3600, "token_type": "Bearer" }
```

All subsequent requests use `Authorization: Bearer <token>`.

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/pfs` | Station metadata (name, address, postcode, lat/lon, brand) |
| `GET` | `/api/v1/pfs/fuel-prices` | Current fuel prices per station |

Both use `?batch-number=N` pagination. The client increments batch number until the API returns 404 (end of data).

### Fuel types

| Code | Description |
|------|-------------|
| `E10` | Standard unleaded petrol |
| `E5` | Super unleaded / premium petrol |
| `B7` | Standard diesel |
| `SDV` | Super diesel / premium diesel |

Prices from the API are in **pence per litre** when > 100. The client normalises to £/L automatically.

The API uses non-canonical fuel type names that are normalised via `_FUEL_TYPE_ALIASES` in `fetch_prices.py`:
- `B7_STANDARD` → `B7`
- `B7_PREMIUM` → `SDV`
- `UNLEADED` → `E10`, `DIESEL` → `B7`, etc.

---

## Architecture

```
config_flow.py          credentials → location geocoding → options
       │
       ▼
__init__.py             creates FuelPricesDataUpdateCoordinator
       │
       ▼
fetch_prices.py         asyncio.gather(get_all_stations, get_all_fuel_prices)
                        → merges on site_id / node_id
                        → haversine radius filter
                        → fuel type filter (only stations with at least one configured fuel type)
       │
       ▼
sensor.py               reads coordinator.data
                        CheapestFuelPriceSensor  (sorted by price asc)
                        NearestFuelStationSensor (sorted by distance asc)
                        StationSensor            (sorted by distance; state = cheapest price)
```

### `FuelPricesDataUpdateCoordinator` (`__init__.py`)

- Extends `DataUpdateCoordinator[list[dict]]`.
- On startup fires a background refresh, staggered by 15 s per config entry to avoid simultaneous API bursts when multiple locations are configured.
- Retries once after 30 s if the initial refresh fails.
- Optionally overrides lat/lon from a `device_tracker` entity for mobile tracking.
- `always_update=False` — suppresses HA state writes when data is unchanged.
- Passes `self._fuel_types` (the user's configured fuel types) to `fetch_stations_by_criteria`, so the radius filter only excludes stations that lack *all* of the user's requested fuels.

### `FuelPricesAPI` (`api_client.py`)

- Module-level `_TOKEN_CACHE` keyed on `(client_id, client_secret)` — multiple config entries sharing the same credentials share one token, halving auth requests.
- Module-level `_RATE_LIMIT_UNTIL` — shared backoff timer so concurrent entries don't independently hammer the API after a 429.
- Retries up to 4 times with exponential back-off on network errors; honours `Retry-After` on 429.
- `_fetch_all_pages()` helper pages until 404 is returned (end-of-data signal).
- `_extract_records()` walks nested API responses to locate the records list regardless of key name.

### Location geocoding (`config_flow._geocode`)

1. **Postcodes.io** (`api.postcodes.io`) — tried first; fast and authoritative for UK postcodes, no auth required.
2. **Nominatim** (OpenStreetMap) — fallback for town names, addresses, and partial postcodes.

Both use `async_get_clientsession(hass)` — HA's shared `aiohttp` session.

### Sensors (`sensor.py`)

`CheapestFuelPriceSensor` — filters stations with a valid, non-stale price for the target fuel type, sorts by `(price, site_id)`, returns the Nth entry. State = £/L (3 dp).

`NearestFuelStationSensor` — same filter, sorts by `(distance_km, site_id)` instead. State = £/L (3 dp).

`StationSensor` — ranks ALL stations in the coordinator data by distance, regardless of fuel type. State = cheapest available price at that station in £/L. Exposes individual prices for all four fuel types as attributes (`e10_price`, `e5_price`, `b7_price`, `sdv_price`).

Key attributes on all sensors: `station_name`, `brand`, `address`, `postcode`, `latitude`, `longitude`, `distance_km`, `distance_miles`, `last_updated`.

---

## Configuration options

| Key | Default | Range | Description |
|-----|---------|-------|-------------|
| `client_id` | — | — | API Client ID |
| `client_secret` | — | — | API Client Secret |
| Location method | `address` | home / address / coordinates | How the search centre is set |
| Postcode / address | — | — | UK postcode or place name |
| `radius` (stored as km) | 8 km (~5 mi) | 0.8–50 km | Search radius |
| `fuel_types` | `[E10, B7]` | any subset | Which fuel types to track |
| `cheapest_count` | 3 | 1–5 | Cheapest-price sensors per fuel type |
| `nearest_count` | 0 | 0–5 | Nearest-station sensors per fuel type |
| `station_count` | 3 | 0–50 | Nearby station sensors (all-fuel attributes) |
| `update_interval` | 3600 s | 300–86400 | Refresh interval |
| `max_data_age_days` | 0 | 0–30 | Drop stale price records (0 = keep all) |

---

## Release process

Releases are published via GitHub Actions because the managed remote execution environment (Claude Code on the web) does not permit pushing git tags through its git proxy.

**To publish a release:**

1. Go to **Actions → Create Release → Run workflow** on GitHub
2. Enter the version string (e.g. `2.0.0`)
3. Optionally add extra release notes
4. Click **Run workflow**

The workflow (`release.yml`) will:
- Create and push the annotated git tag
- Generate release notes
- Publish the GitHub release via `softprops/action-gh-release`

The `version` field in `manifest.json` must match the tag. Update it before triggering the workflow if bumping the version.

---

## Key design decisions

| Decision | Reason |
|----------|--------|
| No `geopy` dependency | Geocoding done via `postcodes.io` + Nominatim over `aiohttp` (HA core dep). Avoids extra wheel install. |
| Custom haversine in `fetch_prices.py` | Same reason — no geopy needed for distance. |
| Shared token + rate-limit state at module level | Multiple config entries for different locations but same credentials reuse one token and coordinate 429 back-off. |
| Prices > 100 divided by 100 | API sometimes returns pence; this normalises to £/L without knowing the API contract precisely. |
| `always_update=False` on coordinator | Prevents unnecessary HA state writes and recorder DB churn when the API returns identical data. |
| Postcodes.io before Nominatim | Postcodes.io is authoritative and instant for UK postcodes; Nominatim is the fallback for free-text queries. |
| `self._fuel_types` passed to fetch | Coordinator passes the user's configured fuel types so the "no matching price" station filter is correctly scoped. |
| StationSensor state = cheapest price | Distance (the previous state) is less useful for automations and dashboards than knowing what you'd pay. Distance is still available as an attribute. |
| Diagnostic logs at DEBUG | Verbose API shape / coverage logs are DEBUG only; INFO is reserved for meaningful operational events (station count found, warnings on empty results). |

---

## Development

### Install dev dependencies

```bash
pip install homeassistant pytest pytest-homeassistant-custom-component aiohttp aioresponses
```

### Run tests

```bash
pytest tests/
```

### Lint

```bash
pip install ruff
ruff check custom_components/
```

### Standalone API diagnostic

```bash
python3 test_api.py <client_id> <client_secret> [postcode_or_coords]
```

### Bump version

1. Update `version` in `custom_components/fuel_prices_uk/manifest.json`
2. Commit to main
3. Trigger the **Create Release** workflow with the new version string

---

## Useful links

- [Fuel Finder developer portal](https://www.developer.fuel-finder.service.gov.uk)
- [GOV.UK — access fuel price data](https://www.gov.uk/guidance/access-the-latest-fuel-prices-and-forecourt-data-via-api-or-email)
- [Home Assistant integration manifest docs](https://developers.home-assistant.io/docs/creating_integration_manifest)
- [HACS custom repository docs](https://hacs.xyz/docs/publish/integration)
- [Postcodes.io API](https://postcodes.io)
