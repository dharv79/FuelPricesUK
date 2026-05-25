# Fuel Prices UK

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue.svg)](https://www.home-assistant.io)
[![License](https://img.shields.io/github/license/dharv79/FuelPricesUK)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-green.svg)](https://github.com/dharv79/FuelPricesUK/releases)

A Home Assistant custom integration that surfaces live UK petrol-station fuel prices as sensors, powered by the **UK Government Fuel Finder** open data scheme.

> Data source: [developer.fuel-finder.service.gov.uk](https://www.developer.fuel-finder.service.gov.uk) — official government-collected fuel prices, updated throughout the day. Stations are legally required to report price changes within 30 minutes.

---

## Features

- **Four fuel types** — E10 (petrol), E5 (super unleaded), B7 (diesel), SDV (super diesel)
- **Cheapest sensors** — up to 5 ranked cheapest-price stations per fuel type
- **Nearest sensors** — up to 5 ranked nearest stations per fuel type (with valid price)
- **Station sensors** — ranked nearby stations with all available fuel prices as attributes
- **Flexible location** — search by UK postcode, town/address, manual coordinates, or HA home location
- **Multiple locations** — add the integration more than once to track home, work, or any other area simultaneously
- **Configurable refresh** — 5 minutes to 24 hours
- **Data age filter** — ignore price records older than N days
- **Full config UI** — set up entirely through Settings → Devices & Services, no YAML needed
- **OAuth2 authentication** — free credentials from the government developer portal

---

## Prerequisites

You need **free API credentials** from the UK Government Fuel Finder developer portal:

1. Register at [developer.fuel-finder.service.gov.uk](https://www.developer.fuel-finder.service.gov.uk)
2. Create an application to receive a **Client ID** and **Client Secret**
3. Keep these handy — you will enter them during integration setup

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three-dot menu → **Custom repositories**
3. Add `https://github.com/dharv79/FuelPricesUK` with category **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/fuel_prices_uk/` folder into your HA `config/custom_components/` directory
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Fuel Prices UK**
3. Follow the three-step wizard:

### Step 1 — API Credentials

| Field | Description |
|-------|-------------|
| **Client ID** | From the Fuel Finder developer portal |
| **Client Secret** | From the Fuel Finder developer portal |

### Step 2 — Location

Choose how to set your search location:

| Method | Description |
|--------|-------------|
| **Postcode / Address** | Enter a UK postcode (e.g. `SW1A 1AA`) or town name (e.g. `Manchester`) |
| **Coordinates** | Enter latitude and longitude directly |
| **HA Home Location** | Use the location configured in HA settings |

### Step 3 — Options

| Option | Default | Description |
|--------|---------|-------------|
| Search radius | 5 miles | How far to search from your location (0.5 – 31 miles) |
| E10 (Petrol) | On | Track standard unleaded prices |
| E5 (Super Unleaded) | Off | Track premium petrol prices |
| B7 (Diesel) | On | Track standard diesel prices |
| SDV (Super Diesel) | Off | Track premium diesel prices |
| Cheapest sensors | 3 | Cheapest-price sensors per fuel type (1–5) |
| Nearest sensors | 0 | Nearest-station sensors per fuel type (0–5) |
| Station sensors | 3 | Nearby station sensors showing all prices (0–50) |
| Update interval | 3600 s | How often to refresh prices (300–86400 seconds) |
| Max data age | 0 days | Ignore price records older than N days (0 = show all) |

---

## Sensors

### Cheapest price sensors

One sensor per fuel type per rank. State = price in **£/L**.

```
sensor.fuel_prices_uk_cheapest_e10        ← cheapest E10 nearby
sensor.fuel_prices_uk_2nd_cheapest_e10
sensor.fuel_prices_uk_3rd_cheapest_e10
```

| Attribute | Example | Description |
|-----------|---------|-------------|
| `fuel_type` | `E10` | Fuel code |
| `fuel_type_label` | `E10 (Petrol)` | Human-readable fuel name |
| `price_rank` | `1` | Rank (1 = cheapest) |
| `station_name` | `Tesco Lewisham` | Forecourt name |
| `brand` | `Tesco` | Brand / retailer |
| `address` | `High Street, Lewisham` | Street address |
| `postcode` | `SE13 6JZ` | Station postcode |
| `latitude` / `longitude` | `51.4615` / `-0.0134` | Station coordinates |
| `distance_km` / `distance_miles` | `1.243` / `0.77` | Distance from search point |
| `site_id` | `1234567` | Government site identifier |
| `last_updated` | `2026-05-25T10:30:00Z` | When price was last reported |
| `e10_price`, `b7_price`, … | `1.439` | All fuel prices at this station |

### Nearest station sensors

Same attributes as cheapest sensors, sorted by distance instead of price.

```
sensor.fuel_prices_uk_1st_nearest_e10
sensor.fuel_prices_uk_2nd_nearest_e10
```

Extra attribute: `distance_rank`.

### Station sensors

One sensor per rank showing the **cheapest available price** at that station as state. All four fuel prices are exposed as attributes, making these ideal for dashboard cards and automations.

```
sensor.fuel_prices_uk_station_1    ← nearest station (cheapest price as state)
sensor.fuel_prices_uk_station_2
sensor.fuel_prices_uk_station_3
```

| Attribute | Example | Description |
|-----------|---------|-------------|
| `station_name` | `BP Catford` | Forecourt name |
| `brand` | `BP` | Brand / retailer |
| `address` / `postcode` | `Rushey Green` / `SE6 4AS` | Location |
| `latitude` / `longitude` | `51.4432` / `-0.0198` | Coordinates |
| `distance_km` / `distance_miles` | `2.1` / `1.3` | Distance from search point |
| `distance_rank` | `1` | Rank by distance |
| `e10_price` | `1.439` | E10 price (null if not sold) |
| `e5_price` | `1.519` | E5 price (null if not sold) |
| `b7_price` | `1.489` | B7 price (null if not sold) |
| `sdv_price` | `1.569` | SDV price (null if not sold) |
| `e10_last_updated` | `2026-05-25T10:30:00Z` | When E10 price was last reported |
| `cheapest_fuel_type` | `E10` | Which fuel is cheapest at this station |
| `cheapest_price` | `1.439` | Cheapest price across all fuels |
| `site_id` | `1234567` | Government site identifier |

---

## Example dashboard card

```yaml
type: entities
title: Cheapest Petrol Nearby
entities:
  - entity: sensor.fuel_prices_uk_cheapest_e10
    name: Cheapest E10
  - entity: sensor.fuel_prices_uk_2nd_cheapest_e10
    name: 2nd Cheapest E10
  - entity: sensor.fuel_prices_uk_3rd_cheapest_e10
    name: 3rd Cheapest E10
```

```yaml
type: entities
title: Nearest Stations
entities:
  - entity: sensor.fuel_prices_uk_station_1
    name: Nearest station
  - entity: sensor.fuel_prices_uk_station_2
    name: 2nd nearest
  - entity: sensor.fuel_prices_uk_station_3
    name: 3rd nearest
```

---

## Fuel type reference

| Code | Full name | Description |
|------|-----------|-------------|
| E10 | Unleaded Petrol | Standard petrol — most common |
| E5 | Super Unleaded | Premium petrol (95/98 RON) |
| B7 | Diesel | Standard diesel |
| SDV | Super Diesel | Premium / additive diesel |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `unavailable` on all sensors | Bad API credentials | Reconfigure and re-enter Client ID / Secret |
| No stations found | Radius too small or remote location | Increase search radius in Options |
| Stale prices | `max_data_age_days` too strict | Increase the value or set to 0 |
| `cannot_connect` error | Network issue or API outage | Check your network; API may be under maintenance |
| Station sensors show wrong unit warning in logs | Old `mi` statistics from v1.x | See migration note below |

---

## Migrating from v1.x

In v1.x the Station sensors (`sensor.fuel_prices_uk_station_N`) reported **distance in miles** as their state. In v2.0.0 they report the **cheapest fuel price in £/L** at that station, which is more useful for dashboards and automations.

If you see recorder warnings about unit mismatch (`GBP/L` vs `mi`) after upgrading, clear the old statistics:

1. Go to **Developer Tools → Statistics** (or use the link in the warning)
2. Find each `fuel_prices_uk_station_N` sensor
3. Click the **Fix issue** button and choose to clear the statistics

The sensors will then record cleanly under the new `GBP/L` unit.

---

## Data source & attribution

Fuel prices are provided by the **UK Government Fuel Finder scheme** under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

---

## License

[Apache 2.0](LICENSE)
