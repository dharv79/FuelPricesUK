"""Async client for the UK Government Fuel Finder API."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_TOKEN_PATH,
    API_STATIONS_PATH,
    API_PRICES_PATH,
)

_LOGGER = logging.getLogger(__name__)

# Shared token cache across all instances with the same credentials.
# Key: (client_id, client_secret) → (access_token, expiry_unix_timestamp)
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}
_TOKEN_LOCK = asyncio.Lock()

# Global rate-limit coordination — shared across all config entries.
_RATE_LIMIT_UNTIL: float = 0.0
_RATE_LIMIT_LOCK = asyncio.Lock()

# Minimum gap between any two API requests (enforced globally).
_MIN_REQUEST_INTERVAL = 2.05  # seconds
_LAST_REQUEST_AT: float = 0.0


class ApiHttpError(Exception):
    """Raised when the API returns an unexpected HTTP status."""

    def __init__(self, status: int, message: str = "") -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {message}")


class FuelPricesAPI:
    """Lightweight async client for the UK Government Fuel Finder REST API."""

    def __init__(self, hass: Any, client_id: str, client_secret: str) -> None:
        self._hass = hass
        self._client_id = client_id
        self._client_secret = client_secret
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _get_token(self) -> str:
        """Return a valid access token, refreshing from API if expired."""
        cache_key = (self._client_id, self._client_secret)
        async with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
            if cached and time.time() < cached[1] - 30:
                return cached[0]

            _LOGGER.debug("Requesting new OAuth token from Fuel Finder API")
            url = f"{API_BASE_URL}{API_TOKEN_PATH}"
            session = self._session_get()
            async with session.post(
                url,
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise ApiHttpError(resp.status, text[:200])
                data = await resp.json()

            # Token may be at top level or nested under a "data" key.
            payload = data.get("data", data) if isinstance(data, dict) else data
            token: str = (
                payload.get("access_token")
                or payload.get("token")
                or data.get("access_token")
                or data.get("token", "")
            )
            if not token:
                raise ApiHttpError(200, f"No token in response: {str(data)[:200]}")
            expires_in = int(payload.get("expires_in") or data.get("expires_in") or 3600)
            _TOKEN_CACHE[cache_key] = (token, time.time() + expires_in)
            _LOGGER.debug("New token obtained, expires in %ds", expires_in)
            return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated API request with rate-limit backoff and retry."""
        global _RATE_LIMIT_UNTIL, _LAST_REQUEST_AT

        for attempt in range(4):
            # Enforce minimum inter-request interval.
            async with _RATE_LIMIT_LOCK:
                now = time.time()
                gap = _MIN_REQUEST_INTERVAL - (now - _LAST_REQUEST_AT)
                if gap > 0:
                    await asyncio.sleep(gap)
                wait = _RATE_LIMIT_UNTIL - time.time()
                if wait > 0:
                    _LOGGER.debug("Rate-limit cooldown — waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                _LAST_REQUEST_AT = time.time()

            token = await self._get_token()
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {token}"
            headers["Accept"] = "application/json"

            session = self._session_get()
            try:
                async with session.request(
                    method,
                    f"{API_BASE_URL}{path}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                    **kwargs,
                ) as resp:
                    if resp.status == 429:
                        retry_after = int(
                            resp.headers.get("Retry-After", str(30 * (2**attempt)))
                        )
                        async with _RATE_LIMIT_LOCK:
                            _RATE_LIMIT_UNTIL = max(
                                _RATE_LIMIT_UNTIL, time.time() + retry_after
                            )
                        _LOGGER.warning(
                            "Rate limited; retrying after %ds (attempt %d/4)",
                            retry_after,
                            attempt + 1,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status not in (200, 206):
                        text = await resp.text()
                        raise ApiHttpError(resp.status, text[:200])
                    return await resp.json()
            except aiohttp.ClientError as exc:
                if attempt < 3:
                    backoff = 2**attempt
                    _LOGGER.warning(
                        "Request failed (%s); retrying in %ds", exc, backoff
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise

        raise ApiHttpError(429, "Exceeded retry attempts due to rate limiting")

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_stations(self, batch_number: int = 1) -> dict[str, Any]:
        """Fetch one batch of station metadata."""
        return await self._request(
            "GET", API_STATIONS_PATH, params={"batch-number": batch_number}
        )

    async def get_fuel_prices(self, batch_number: int = 1) -> dict[str, Any]:
        """Fetch one batch of current fuel prices."""
        return await self._request(
            "GET", API_PRICES_PATH, params={"batch-number": batch_number}
        )

    async def get_all_stations(self) -> list[dict[str, Any]]:
        """Fetch every station record across all batches."""
        return await _fetch_all_pages(self.get_stations)

    async def get_all_fuel_prices(self) -> list[dict[str, Any]]:
        """Fetch every price record across all batches."""
        return await _fetch_all_pages(self.get_fuel_prices)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _fetch_all_pages(page_fn: Any) -> list[dict[str, Any]]:
    """Call page_fn(batch_number=N) repeatedly until the API returns 404 (no more batches)."""
    records: list[dict[str, Any]] = []
    batch_number = 1
    while True:
        try:
            data = await page_fn(batch_number=batch_number)
        except ApiHttpError as exc:
            if exc.status == 404:
                break  # API signals end-of-data with 404, not an empty response
            raise
        batch = _extract_records(data)
        if not batch:
            break
        records.extend(batch)
        batch_number += 1
    return records


def _extract_records(data: Any) -> list[dict[str, Any]]:
    """Locate the list of records inside an API response regardless of nesting."""
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
