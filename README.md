# Fuel Prices UK

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue.svg)](https://www.home-assistant.io)
[![License](https://img.shields.io/github/license/dharv79/FuelPricesUK)](LICENSE)

A Home Assistant custom integration that surfaces live UK petrol-station fuel prices as sensors, powered by the **UK Government Fuel Finder** open data scheme.

> Data source: [developer.fuel-finder.service.gov.uk](https://www.developer.fuel-finder.service.gov.uk) — official government-collected fuel prices updated throughout the day.

---

## Features

- 🔍 **Search by postcode, town name, address, or lat/lon**
- ⛽ **Four fuel types** — E10 (petrol), E5 (super unleaded), B7 (diesel), SDV (super diesel)
- 📊 **Cheapest sensors** — up to 5 ranked cheapest stations per fuel type
- 📍 **Nearest sensors** — up to 5 ranked nearest stations per fuel type
- 🔄 **Configurable refresh interval** — 5 minutes to 24 hours
- 🔑 **OAuth2 authentication** — uses your API credentials from the developer portal
- 📱 **Full config UI** — set up entirely through Settings → Devices & Services, no YAML needed

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
| E10 (Petrol) | ✅ | Track standard unleaded prices |
| E5 (Super Unleaded) | ❌ | Track premium petrol prices |
| B7 (Diesel) | ✅ | Track standard diesel prices |
| SDV (Super Diesel) | ❌ | Track premium diesel prices |
| Cheapest sensors | 3 | Number of cheapest-price sensors per fuel type (1–5) |
| Nearest sensors | 0 | Number of nearest-station sensors per fuel type (0–5) |
| Update interval | 3600 s | How often to refresh prices (300 – 86400 seconds) |
| Max data age | 1 day | Ignore price records older than N days (0 = show all) |

---

## Sensors

Each configured fuel type produces sensors named:

```
sensor.fuel_prices_uk_<location>_cheapest_<fuel>
sensor.fuel_prices_uk_<location>_2nd_cheapest_<fuel>
sensor.fuel_prices_uk_<location>_3rd_cheapest_<fuel>

sensor.fuel_prices_uk_<location>_1st_nearest_<fuel>
sensor.fuel_prices_uk_<location>_2nd_nearest_<fuel>
```

**State** — price in **£/L** (e.g. `1.439`)

**Attributes**

| Attribute | Example | Description |
|-----------|---------|-------------|
| `fuel_type` | `E10` | Fuel code |
| `fuel_type_label` | `E10 (Petrol)` | Human-readable fuel name |
| `price_rank` | `1` | Rank (1 = cheapest / nearest) |
| `price_rank_label` | `1st cheapest` | Rank as text |
| `station_name` | `Tesco Lewisham` | Forecourt name |
| `brand` | `Tesco` | Brand / retailer |
| `address` | `High Street, Lewisham` | Street address |
| `postcode` | `SE13 6JZ` | Station postcode |
| `latitude` | `51.4615` | Station latitude |
| `longitude` | `-0.0134` | Station longitude |
| `distance_km` | `1.243` | Distance from search point (km) |
| `distance_miles` | `0.77` | Distance from search point (miles) |
| `site_id` | `1234567` | Government site identifier |
| `last_updated` | `2026-05-25T10:30:00Z` | When price was last reported |

---

## Example dashboard card

```yaml
type: entities
title: Cheapest Petrol Nearby
entities:
  - entity: sensor.fuel_prices_uk_sw1a_1aa_cheapest_e10
    name: Cheapest E10
  - entity: sensor.fuel_prices_uk_sw1a_1aa_2nd_cheapest_e10
    name: 2nd Cheapest E10
  - entity: sensor.fuel_prices_uk_sw1a_1aa_3rd_cheapest_e10
    name: 3rd Cheapest E10
```

---

## Multiple locations

Add the integration more than once (each with a different postcode or address) to track prices near home, work, or any other location simultaneously.

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
| `cannot_connect` error | Network issue or API outage | Check [status.fuel-finder.service.gov.uk](https://www.fuel-finder.service.gov.uk) |

---

## Data source & attribution

Fuel prices are provided by the **UK Government Fuel Finder scheme** under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

Petrol stations are legally required to report fuel prices to the scheme within 30 minutes of a price change.

---

## License

[Apache 2.0](LICENSE)
