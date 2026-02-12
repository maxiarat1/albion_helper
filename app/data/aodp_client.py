"""Client for the Albion Online Data Project (AODP) API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import AODPConfig

logger = logging.getLogger(__name__)


class AODPError(RuntimeError):
    """Raised when the AODP API returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class AODPClient:
    """Async HTTP client for AODP."""

    def __init__(self, base_url: str | None = None, timeout_s: float | None = None) -> None:
        config = AODPConfig()
        self._base_url = (base_url or config.base_url).rstrip("/")
        self._timeout_s = timeout_s or config.timeout_s
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AODPClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def base_url(self) -> str:
        """Return the configured base URL (for logging/debugging)."""
        return self._base_url

    async def get_prices(
        self,
        item_id: str,
        *,
        locations: list[str],
        qualities: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch current market prices for an item.

        Returns list of price entries with timestamps for freshness checking:
        - sell_price_min, sell_price_min_date
        - sell_price_max, sell_price_max_date
        - buy_price_min, buy_price_min_date
        - buy_price_max, buy_price_max_date
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        params: dict[str, str] = {"locations": ",".join(locations)}
        if qualities:
            params["qualities"] = ",".join(str(q) for q in qualities)

        endpoint = f"/api/v2/stats/prices/{item_id}.json"
        logger.info("[AODP] Fetching prices: item=%s locations=%s url=%s", item_id, params["locations"], self._base_url)
        response = await self._client.get(endpoint, params=params)
        return self._handle_response(response)

    async def get_history(
        self,
        item_id: str,
        *,
        locations: list[str],
        qualities: list[int] | None = None,
        time_scale: int = 1,
        date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical price data for an item.

        Args:
            item_id: Item unique name (e.g., T4_BAG)
            locations: List of city names
            qualities: Optional list of quality levels (1-5)
            time_scale: Data granularity - 1 for hourly, 24 for daily
            date: Start date (YYYY-MM-DD format)
            end_date: End date (YYYY-MM-DD format)

        Returns:
            List of historical price entries with timestamps and aggregated values.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        params: dict[str, str] = {
            "locations": ",".join(locations),
            "time-scale": str(time_scale),
        }
        if qualities:
            params["qualities"] = ",".join(str(q) for q in qualities)
        if date:
            params["date"] = date
        if end_date:
            params["end_date"] = end_date

        endpoint = f"/api/v2/stats/history/{item_id}.json"
        logger.info(
            "[AODP] Fetching history: item=%s locations=%s time_scale=%d url=%s",
            item_id, params["locations"], time_scale, self._base_url
        )
        response = await self._client.get(endpoint, params=params)
        return self._handle_response(response)

    async def get_gold_prices(
        self,
        *,
        count: int | None = None,
        date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch gold-to-silver exchange rate history.

        Returns list of entries with {price, timestamp}.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        params: dict[str, str] = {}
        if count is not None:
            params["count"] = str(count)
        if date:
            params["date"] = date
        if end_date:
            params["end_date"] = end_date

        endpoint = "/api/v2/stats/gold.json"
        logger.info("[AODP] Fetching gold prices: params=%s url=%s", params, self._base_url)
        response = await self._client.get(endpoint, params=params)
        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> list[dict[str, Any]]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            payload: Any | None = None
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            raise AODPError(
                f"AODP API error ({response.status_code}).",
                status_code=response.status_code,
                payload=payload,
            ) from exc

        data = response.json()
        if isinstance(data, list):
            return data
        return []
