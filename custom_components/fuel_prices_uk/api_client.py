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
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise ApiHttpError(resp.status, text[:200])
                data = await resp.json()

            token: str = data.get("access_token") or data.get("token", "")
            if not token:
                raise ApiHttpError(200, "No token in response")
            expires_in = int(data.get("expires_in", 3600))
            _TOKEN_CACHE[cache_key] = (token, time.time() + expires_in)
            _LOGGER.debug("New token obtained, expires in %ds", expires_in)
            return token

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Make an authenticated API request with rate-limit backoff and retry."""
        global _RATE_LIMIT_UNTIL

        for attempt in range(4):
            async with _RATE_LIMIT_LOCK:
                wait = _RATE_LIMIT_UNTIL - time.time()
                if wait > 0:
                    _LOGGER.debug("Rate-limit cooldown — waiting %.1fs", wait)
            if wait > 0:
                await asyncio.sleep(wait)

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

    async def get_stations(
        self, page: int = 1, page_size: int = 500
    ) -> dict[str, Any]:
        """Fetch one page of station metadata."""
        return await self._request(
            "GET", API_STATIONS_PATH, params={"page": page, "pageSize": page_size}
        )

    async def get_fuel_prices(
        self, page: int = 1, page_size: int = 500
    ) -> dict[str, Any]:
        """Fetch one page of current fuel prices."""
        return await self._request(
            "GET", API_PRICES_PATH, params={"page": page, "pageSize": page_size}
        )

    async def get_all_stations(self) -> list[dict[str, Any]]:
        """Fetch every station record, paging until exhausted."""
        return await _fetch_all_pages(self.get_stations)

    async def get_all_fuel_prices(self) -> list[dict[str, Any]]:
        """Fetch every price record, paging until exhausted."""
        return await _fetch_all_pages(self.get_fuel_prices)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _fetch_all_pages(
    page_fn: Any, page_size: int = 500
) -> list[dict[str, Any]]:
    """Call page_fn(page=N, page_size=page_size) repeatedly until no more records."""
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        data = await page_fn(page=page, page_size=page_size)
        batch = _extract_records(data)
        if not batch:
            break
        records.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
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
