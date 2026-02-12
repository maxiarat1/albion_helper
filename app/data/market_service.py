"""Market data service for Albion Helper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dateparser

from .aodp_client import AODPClient, AODPError
from .cache import TTLCache
from .catalog import ItemResolution, ItemResolver
from .config import AODPConfig

logger = logging.getLogger(__name__)

# AODP uses year-1 dates as sentinel for "no data recorded".
_NO_DATA_YEAR = 1


@dataclass(frozen=True)
class MarketServiceError(RuntimeError):
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


@dataclass
class FreshnessInfo:
    """Information about data freshness after filtering."""
    max_age_s: float
    total_entries: int
    fresh_entries: int
    stale_entries: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_age_seconds": self.max_age_s,
            "max_age_minutes": round(self.max_age_s / 60, 1),
            "total_entries": self.total_entries,
            "fresh_entries": self.fresh_entries,
            "stale_entries": self.stale_entries,
        }


def _is_empty_entry(entry: dict[str, Any]) -> bool:
    """Return True if an API entry has no real price data.

    The AODP API returns entries for every (city, quality) combination
    even when no data exists.  These empty entries have all four price
    fields set to 0 and sentinel dates of ``0001-01-01T00:00:00``.
    """
    return (
        not entry.get("sell_price_min")
        and not entry.get("sell_price_max")
        and not entry.get("buy_price_min")
        and not entry.get("buy_price_max")
    )


class MarketService:
    """Service layer for market data access and normalization."""

    def __init__(
        self,
        *,
        cache: TTLCache,
        resolver: ItemResolver,
        base_url: str | None = None,
        timeout_s: float | None = None,
        freshness_ttl_s: float | None = None,
    ) -> None:
        config = AODPConfig()
        self._cache = cache
        self._resolver = resolver
        self._base_url = base_url or config.base_url
        self._timeout_s = timeout_s or config.timeout_s
        self._freshness_ttl_s = freshness_ttl_s if freshness_ttl_s is not None else config.freshness_ttl_s
        self._region = config.region

    @classmethod
    def from_env(cls) -> "MarketService":
        config = AODPConfig()
        return cls(
            cache=TTLCache(config.cache_ttl_s),
            resolver=ItemResolver.from_env(),
            base_url=config.base_url,
            timeout_s=config.timeout_s,
            freshness_ttl_s=config.freshness_ttl_s,
        )

    @property
    def region(self) -> str:
        """Return the configured region."""
        return self._region

    @property
    def freshness_ttl_s(self) -> float:
        """Return the configured freshness TTL in seconds."""
        return self._freshness_ttl_s

    def _parse_timestamp(self, date_str: str | None) -> datetime | None:
        """Parse an ISO timestamp string to datetime.

        Returns ``None`` for missing values *and* for the AODP sentinel
        date ``0001-01-01T00:00:00`` which means "no data recorded".
        """
        if not date_str:
            return None
        try:
            dt = dateparser.isoparse(date_str)
        except (ValueError, TypeError):
            return None
        # AODP sentinel: year 1 means "never"
        if dt.year <= _NO_DATA_YEAR:
            return None
        return dt

    @staticmethod
    def _clean_date(date_str: str | None) -> str | None:
        """Return *None* instead of the AODP sentinel date string."""
        if not date_str:
            return None
        if date_str.startswith("0001-"):
            return None
        return date_str

    @staticmethod
    def _normalize_quantity(value: Any) -> int | None:
        """Parse and validate quantity-like values from API payloads."""
        if value is None:
            return None
        try:
            qty = int(value)
        except (TypeError, ValueError):
            return None
        return qty if qty > 0 else None

    @staticmethod
    def _per_item_price(value: Any, quantity: int | None) -> float | None:
        """Normalize stack price to per-item price."""
        if value is None:
            return None
        try:
            price = float(value)
        except (TypeError, ValueError):
            return None
        divisor = quantity if quantity and quantity > 0 else 1
        return price / divisor

    def _filter_by_freshness(
        self,
        entries: list[dict[str, Any]],
        max_age_s: float,
        now: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], FreshnessInfo]:
        """Filter entries by timestamp freshness.

        Uses sell_price_min_date as the primary freshness indicator.
        Entries without a valid timestamp are marked as stale.

        Returns:
            Tuple of (filtered_entries, freshness_info)
        """
        return self._scan_freshness(entries=entries, max_age_s=max_age_s, now=now, include_entries=True)

    def _scan_freshness(
        self,
        *,
        entries: list[dict[str, Any]],
        max_age_s: float,
        now: datetime | None,
        include_entries: bool,
    ) -> tuple[list[dict[str, Any]], FreshnessInfo]:
        if now is None:
            now = datetime.now(timezone.utc)

        parse_timestamp = self._parse_timestamp
        fresh_entries: list[dict[str, Any]] = []
        stale_count = 0

        for entry in entries:
            timestamp = parse_timestamp(entry.get("sell_price_min_date"))
            if timestamp is None:
                stale_count += 1
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            age_s = (now - timestamp).total_seconds()
            if age_s > max_age_s:
                stale_count += 1
                continue

            if include_entries:
                fresh_entries.append({**entry, "age_seconds": round(age_s, 1)})

        freshness_info = FreshnessInfo(
            max_age_s=max_age_s,
            total_entries=len(entries),
            fresh_entries=len(entries) - stale_count,
            stale_entries=stale_count,
        )
        return fresh_entries, freshness_info

    def resolve_item(self, name: str) -> ItemResolution | None:
        return self._resolver.resolve(name)

    @staticmethod
    def _validate_item(item: str) -> str:
        item = item.strip()
        if not item:
            raise MarketServiceError("Item is required", status_code=400)
        return item

    @staticmethod
    def _validate_cities(cities: list[str]) -> list[str]:
        normalized = [city.strip() for city in cities if city and city.strip()]
        if not normalized:
            raise MarketServiceError("At least one city is required", status_code=400)
        return normalized

    def _resolve_item_or_error(self, item: str) -> ItemResolution:
        resolution = self._resolver.resolve(item)
        if not resolution:
            raise MarketServiceError("Unable to resolve item name", status_code=400)
        return resolution

    @staticmethod
    def _qualities_arg(quality: int | None) -> list[int] | None:
        return [quality] if quality is not None else None

    @staticmethod
    def _time_scale_arg(time_scale: str) -> int:
        return 1 if time_scale == "hourly" else 24

    @staticmethod
    def _prices_cache_key(item_id: str, cities: list[str], quality: int | None) -> str:
        return f"prices:{item_id}:{','.join(cities)}:{quality if quality is not None else 'any'}"

    async def _fetch_prices_entries(
        self,
        *,
        item_id: str,
        cities: list[str],
        qualities: list[int] | None,
    ) -> list[dict[str, Any]]:
        try:
            async with AODPClient(base_url=self._base_url, timeout_s=self._timeout_s) as client:
                return await client.get_prices(item_id, locations=cities, qualities=qualities)
        except AODPError as exc:
            raise MarketServiceError(str(exc), status_code=502) from exc
        except Exception as exc:
            raise MarketServiceError(str(exc), status_code=500) from exc

    async def _fetch_history_entries(
        self,
        *,
        item_id: str,
        cities: list[str],
        qualities: list[int] | None,
        time_scale: int,
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict[str, Any]]:
        try:
            async with AODPClient(base_url=self._base_url, timeout_s=self._timeout_s) as client:
                return await client.get_history(
                    item_id,
                    locations=cities,
                    qualities=qualities,
                    time_scale=time_scale,
                    date=start_date,
                    end_date=end_date,
                )
        except AODPError as exc:
            raise MarketServiceError(str(exc), status_code=502) from exc
        except Exception as exc:
            raise MarketServiceError(str(exc), status_code=500) from exc

    async def _fetch_recent_gold_entries(self, *, count: int = 48) -> list[dict[str, Any]]:
        async with AODPClient(base_url=self._base_url, timeout_s=self._timeout_s) as client:
            return await client.get_gold_prices(count=count)

    def _normalize_price_entry(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        if _is_empty_entry(entry):
            return None

        quantity = self._normalize_quantity(
            entry.get("item_count")
            or entry.get("quantity")
            or entry.get("amount")
        )

        sell_price_min = entry.get("sell_price_min")
        sell_price_max = entry.get("sell_price_max")
        buy_price_min = entry.get("buy_price_min")
        buy_price_max = entry.get("buy_price_max")

        normalized: dict[str, Any] = {
            "location": entry.get("city") or entry.get("location"),
            "quality": entry.get("quality"),
            "sell_price_min": sell_price_min,
            "sell_price_min_date": self._clean_date(entry.get("sell_price_min_date")),
            "sell_price_max": sell_price_max,
            "sell_price_max_date": self._clean_date(entry.get("sell_price_max_date")),
            "buy_price_min": buy_price_min,
            "buy_price_min_date": self._clean_date(entry.get("buy_price_min_date")),
            "buy_price_max": buy_price_max,
            "buy_price_max_date": self._clean_date(entry.get("buy_price_max_date")),
        }

        if quantity and quantity > 1:
            normalized["item_count"] = quantity
            normalized["sell_price_min_per_item"] = self._per_item_price(sell_price_min, quantity)
            normalized["sell_price_max_per_item"] = self._per_item_price(sell_price_max, quantity)
            normalized["buy_price_min_per_item"] = self._per_item_price(buy_price_min, quantity)
            normalized["buy_price_max_per_item"] = self._per_item_price(buy_price_max, quantity)
        return normalized

    def _normalize_price_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = []
        append = data.append
        normalize = self._normalize_price_entry
        for entry in entries:
            normalized = normalize(entry)
            if normalized is not None:
                append(normalized)
        return data

    def _apply_freshness(
        self,
        *,
        data: list[dict[str, Any]],
        max_age_s: float,
        filter_stale: bool,
    ) -> tuple[list[dict[str, Any]], FreshnessInfo]:
        if filter_stale:
            return self._filter_by_freshness(data, max_age_s)
        _, freshness_info = self._scan_freshness(
            entries=data,
            max_age_s=max_age_s,
            now=None,
            include_entries=False,
        )
        return data, freshness_info

    @staticmethod
    def _flatten_history_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        data: list[dict[str, Any]] = []
        append = data.append
        extend = data.extend
        for entry in entries:
            location = entry.get("location")
            qual = entry.get("quality")
            inner = entry.get("data")

            if isinstance(inner, list):
                extend(
                    {
                        "location": location,
                        "quality": qual,
                        "timestamp": point.get("timestamp"),
                        "item_count": point.get("item_count"),
                        "avg_price": point.get("avg_price"),
                    }
                    for point in inner
                )
                continue

            append({
                "location": location,
                "quality": qual,
                "timestamp": entry.get("timestamp"),
                "item_count": entry.get("item_count"),
                "avg_price": entry.get("avg_price"),
            })
        return data

    @staticmethod
    def _item_response_payload(query: str, resolution: ItemResolution) -> dict[str, Any]:
        return {
            "query": query,
            "id": resolution.item_id,
            "resolution": resolution.strategy,
            "display_name": resolution.display_name,
        }

    def _build_prices_response(
        self,
        *,
        item: str,
        resolution: ItemResolution,
        cities: list[str],
        quality: int | None,
        data: list[dict[str, Any]],
        freshness_info: FreshnessInfo,
    ) -> dict[str, Any]:
        return {
            "item": self._item_response_payload(item, resolution),
            "locations": cities,
            "quality": quality,
            "data": data,
            "freshness": freshness_info.to_dict(),
            "region": self._region,
            "cached": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": self._base_url,
        }

    def _build_history_response(
        self,
        *,
        item: str,
        resolution: ItemResolution,
        cities: list[str],
        quality: int | None,
        time_scale: str,
        start_date: str | None,
        end_date: str | None,
        data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "item": self._item_response_payload(item, resolution),
            "locations": cities,
            "quality": quality,
            "time_scale": time_scale,
            "start_date": start_date,
            "end_date": end_date,
            "data": data,
            "region": self._region,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source": self._base_url,
        }

    @staticmethod
    def _timestamp_age_hours(now: datetime, timestamp: datetime) -> float:
        return (now - timestamp).total_seconds() / 3600

    def _should_fetch_gold_from_api(
        self,
        *,
        latest_ts_str: str | None,
        now: datetime,
        max_age_hours: float = 2,
    ) -> bool:
        if not latest_ts_str:
            return True
        latest_ts = self._parse_timestamp(latest_ts_str)
        if not latest_ts:
            return True
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        return self._timestamp_age_hours(now, latest_ts) >= max_age_hours

    async def _refresh_gold_from_api_if_needed(
        self,
        *,
        db: Any,
        latest_ts_str: str | None,
        needs_api: bool,
    ) -> str:
        source = "db"
        if not needs_api:
            return source

        try:
            api_data = await self._fetch_recent_gold_entries(count=48)
            if api_data:
                db.insert_gold_prices(api_data)
                source = "api" if not latest_ts_str else "both"
                logger.info("[MarketService] Fetched and stored %d gold price records", len(api_data))
        except Exception as exc:
            logger.warning("[MarketService] Failed to fetch gold prices from API: %s", exc)
            if not latest_ts_str:
                raise MarketServiceError(
                    f"No gold price data available: {exc}", status_code=502
                ) from exc
        return source

    async def get_prices(
        self,
        *,
        item: str,
        cities: list[str],
        quality: int | None = None,
        force_refresh: bool = False,
        max_age_s: float | None = None,
        filter_stale: bool = False,
    ) -> dict[str, Any]:
        """Fetch current market prices for an item.

        Args:
            item: Item name or ID
            cities: List of cities to check
            quality: Optional quality level (1-5)
            force_refresh: Bypass cache
            max_age_s: Max age in seconds for freshness check (default: config value)
            filter_stale: If True, filter out stale entries; if False, mark but keep them

        Returns:
            Dict with price data and freshness info
        """
        item = self._validate_item(item)
        cities = self._validate_cities(cities)
        resolution = self._resolve_item_or_error(item)

        cache_key = self._prices_cache_key(resolution.item_id, cities, quality)
        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached:
                return {**cached, "cached": True}

        entries = await self._fetch_prices_entries(
            item_id=resolution.item_id,
            cities=cities,
            qualities=self._qualities_arg(quality),
        )

        if not entries:
            raise MarketServiceError("No market data found", status_code=404)

        data = self._normalize_price_entries(entries)

        if not data:
            raise MarketServiceError("No market data found", status_code=404)

        effective_max_age = max_age_s if max_age_s is not None else self._freshness_ttl_s
        data, freshness_info = self._apply_freshness(
            data=data,
            max_age_s=effective_max_age,
            filter_stale=filter_stale,
        )

        response = self._build_prices_response(
            item=item,
            resolution=resolution,
            cities=cities,
            quality=quality,
            data=data,
            freshness_info=freshness_info,
        )
        self._cache.set(cache_key, response)
        return response

    async def get_history(
        self,
        *,
        item: str,
        cities: list[str],
        quality: int | None = None,
        time_scale: str = "hourly",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch historical price data for an item.

        The AODP history endpoint returns a nested structure::

            [{"location": "Caerleon", "quality": 1,
              "data": [{"item_count": 50, "avg_price": 2400, "timestamp": "..."}]}]

        We flatten this into a simple list of records for easier consumption.

        Args:
            item: Item name or ID
            cities: List of cities to check
            quality: Optional quality level (1-5)
            time_scale: "hourly" (1) or "daily" (24)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            Dict with historical price data
        """
        item = self._validate_item(item)
        cities = self._validate_cities(cities)
        resolution = self._resolve_item_or_error(item)

        entries = await self._fetch_history_entries(
            item_id=resolution.item_id,
            cities=cities,
            qualities=self._qualities_arg(quality),
            time_scale=self._time_scale_arg(time_scale),
            start_date=start_date,
            end_date=end_date,
        )

        if not entries:
            raise MarketServiceError("No historical data found", status_code=404)

        return self._build_history_response(
            item=item,
            resolution=resolution,
            cities=cities,
            quality=quality,
            time_scale=time_scale,
            start_date=start_date,
            end_date=end_date,
            data=self._flatten_history_entries(entries),
        )

    async def get_gold_prices(
        self,
        *,
        count: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Fetch gold prices, checking DuckDB first and falling back to API.

        Strategy:
        1. Check DuckDB for existing data
        2. If no data for today, fetch recent from AODP API and persist
        3. Return merged results
        """
        from .history_db import get_history_db

        db = get_history_db()
        now = datetime.now(timezone.utc)

        latest_ts_str = db.get_latest_gold_timestamp()
        source = await self._refresh_gold_from_api_if_needed(
            db=db,
            latest_ts_str=latest_ts_str,
            needs_api=self._should_fetch_gold_from_api(
                latest_ts_str=latest_ts_str,
                now=now,
            ),
        )

        data = db.query_gold_prices(
            start_date=start_date,
            end_date=end_date,
            limit=count or 1000,
        )

        latest = data[0] if data else None

        return {
            "data": data,
            "count": len(data),
            "source": source,
            "latest_price": latest["price"] if latest else None,
            "latest_timestamp": latest["timestamp"] if latest else None,
            "region": self._region,
            "fetched_at": now.isoformat(),
        }


default_market_service = MarketService.from_env()
