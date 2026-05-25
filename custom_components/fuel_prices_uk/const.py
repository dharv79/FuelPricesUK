"""Constants for the Fuel Prices UK integration."""

DOMAIN = "fuel_prices_uk"
ENTRY_TITLE = "Fuel Prices UK"

# Config keys
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_LOCATION = "location"
CONF_LOCATION_METHOD = "location_method"
CONF_ADDRESS = "address"
CONF_RADIUS = "radius"
CONF_FUELTYPES = "fuel_types"
CONF_STATIONS = "stations"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_CHEAPEST_COUNT = "cheapest_count"
CONF_NEAREST_COUNT = "nearest_count"
CONF_MAX_DATA_AGE_DAYS = "max_data_age_days"
CONF_DEVICE_TRACKER = "device_tracker"

# Location methods
LOCATION_METHOD_HOME = "home"
LOCATION_METHOD_ADDRESS = "address"
LOCATION_METHOD_COORDINATES = "coordinates"

# Fuel types (UK Government canonical names)
FUEL_TYPE_E10 = "E10"
FUEL_TYPE_E5 = "E5"
FUEL_TYPE_B7 = "B7"
FUEL_TYPE_SDV = "SDV"
FUEL_TYPES = [FUEL_TYPE_E10, FUEL_TYPE_E5, FUEL_TYPE_B7, FUEL_TYPE_SDV]

FUEL_LABELS = {
    FUEL_TYPE_E10: "E10 (Petrol)",
    FUEL_TYPE_E5: "E5 (Super Unleaded)",
    FUEL_TYPE_B7: "B7 (Diesel)",
    FUEL_TYPE_SDV: "SDV (Super Diesel)",
}

# Defaults
DEFAULT_UPDATE_INTERVAL = 3600  # 1 hour in seconds
DEFAULT_RADIUS_KM = 8.0         # ~5 miles
DEFAULT_CHEAPEST_COUNT = 3
DEFAULT_NEAREST_COUNT = 0
DEFAULT_MAX_DATA_AGE_DAYS = 7

MIN_CHEAPEST_COUNT = 1
MAX_CHEAPEST_COUNT = 5
MAX_NEAREST_COUNT = 5

# Unit conversion
MILES_TO_KM = 1.60934
KM_TO_MILES = 1 / MILES_TO_KM

# UK Government Fuel Finder API
API_BASE_URL = "https://www.fuel-finder.service.gov.uk"
API_TOKEN_PATH = "/api/v1/oauth/generate_access_token"
API_STATIONS_PATH = "/api/v1/pfs"
API_PRICES_PATH = "/api/v1/pfs/fuel-prices"

# Sensor attributes
ATTR_FUEL_TYPE = "fuel_type"
ATTR_FUEL_TYPE_LABEL = "fuel_type_label"
ATTR_PRICE_RANK = "price_rank"
ATTR_PRICE_RANK_LABEL = "price_rank_label"
ATTR_STATION_NAME = "station_name"
ATTR_BRAND = "brand"
ATTR_ADDRESS = "address"
ATTR_POSTCODE = "postcode"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_DISTANCE_KM = "distance_km"
ATTR_DISTANCE_MILES = "distance_miles"
ATTR_SITE_ID = "site_id"
ATTR_LAST_UPDATED = "last_updated"
