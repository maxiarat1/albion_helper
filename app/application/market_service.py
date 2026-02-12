"""Application service for market, history, and database workflows."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from app.data import MarketService, MarketServiceError

logger = logging.getLogger(__name__)

DEFAULT_LATEST_MARKET_CITIES = [
    "Caerleon",
    "Thetford",
    "Bridgewatch",
    "Martlock",
    "Fort Sterling",
    "Lymhurst",
    "Black Market",
    "Brecilien",
]

DEFAULT_HISTORY_CITIES = [
    "Caerleon",
    "Bridgewatch",
    "Martlock",
    "Thetford",
    "Fort Sterling",
    "Lymhurst",
    "Black Market",
    "Brecilien",
]


class MarketApplicationService:
    """Single source of truth for market and database use-cases."""

    def __init__(
        self,
        *,
        market_service: MarketService,
        history_db: Any,
        dump_manager: Any,
        item_resolver: Any,
    ) -> None:
        self._market_service = market_service
        self._history_db = history_db
        self._dump_manager = dump_manager
        self._item_resolver = item_resolver

    async def get_market_prices(
        self,
        *,
        item: str,
        cities: list[str],
        quality: int | None = None,
        force_refresh: bool = False,
        max_age_s: float | None = None,
        filter_stale: bool = False,
    ) -> dict[str, Any]:
        return await self._market_service.get_prices(
            item=item,
            cities=cities,
            quality=quality,
            force_refresh=force_refresh,
            max_age_s=max_age_s,
            filter_stale=filter_stale,
        )

    async def get_gold_prices(
        self,
        *,
        count: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await self._market_service.get_gold_prices(
            count=count,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_live_history(
        self,
        *,
        item: str,
        cities: list[str] | None = None,
        quality: int | None = None,
        time_scale: str = "hourly",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        return await self._market_service.get_history(
            item=item,
            cities=cities or DEFAULT_HISTORY_CITIES,
            quality=quality,
            time_scale=time_scale,
            start_date=start_date,
            end_date=end_date,
        )

    def get_local_history(
        self,
        *,
        item_id: str,
        locations: list[str] | None,
        quality: int | None,
        start_date: str | None,
        end_date: str | None,
        granularity: str,
    ) -> list[dict[str, Any]]:
        return self._history_db.get_aggregated_history(
            item_id=item_id,
            locations=locations,
            quality=quality,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )

    def query_local_history_raw(
        self,
        *,
        item_id: str,
        locations: list[str] | None,
        quality: int | None,
        start_date: str | None,
        end_date: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._history_db.query_history(
            item_id=item_id,
            locations=locations,
            quality=quality,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    def resolve_item(self, query: str) -> tuple[str, str]:
        resolution = self._item_resolver.resolve(query, limit=1)
        if not resolution.matches:
            return query, query
        match = resolution.matches[0]
        return match.unique_name, match.display_name

    async def get_db_status(self, *, check_updates: bool = False) -> dict[str, Any]:
        status = self._history_db.get_status()
        result = {
            "database": {
                "initialized": status.initialized,
                "total_records": status.total_records,
                "date_range": {
                    "earliest": status.earliest_date,
                    "latest": status.latest_date,
                },
                "imported_dumps_count": len(status.imported_dumps),
                "imported_dumps": status.imported_dumps[:10],
            },
            "coverage": {
                "months": [month.to_dict() for month in status.coverage_months],
            },
        }

        if not check_updates:
            return result

        try:
            result["updates_available"] = await self.get_db_updates()
        except Exception as exc:
            logger.error("[MarketApplicationService] Error checking updates: %s", exc)
            result["updates_available"] = {"error": str(exc)}
        return result

    async def get_db_updates(self) -> dict[str, Any]:
        available = await self._dump_manager.list_available_dumps()
        recommended = self._dump_manager.get_recommended_dumps(available, max_dumps=1)
        missing = self._dump_manager.get_missing_dumps(available, max_dumps=10)
        daily_available = [dump for dump in available if dump.dump_type == "daily"]
        return {
            "total_available": len(available),
            "daily_available": len(daily_available),
            "pending_import": len(missing),
            "pending_dumps": [dump.to_dict() for dump in missing[:10]],
            "recommended": [dump.to_dict() for dump in recommended],
            "strategy": "latest_daily_full_snapshot",
        }

    async def update_db(self, *, max_dumps: int = 1) -> dict[str, Any]:
        result = await self._dump_manager.update(max_dumps=max_dumps)
        return result.to_dict()

    def get_db_update_progress(self) -> dict[str, Any]:
        return self._dump_manager.get_update_progress()

    def clear_db_update_progress(self) -> dict[str, Any]:
        return self._dump_manager.clear_update_progress()

    def start_db_update(
        self,
        *,
        max_dumps: int = 1,
    ) -> dict[str, Any]:
        return self._dump_manager.start_background_update(max_dumps=max_dumps)

    def reset_db(self, *, cleanup_dumps: bool = True) -> dict[str, Any]:
        reset_result = self._history_db.hard_reset()
        cleaned_dumps = self._cleanup_dump_files(self._dump_manager.download_dir) if cleanup_dumps else []
        return {
            "success": True,
            "reset": reset_result,
            "cleaned_dumps_count": len(cleaned_dumps),
            "cleaned_dumps": cleaned_dumps,
        }

    def get_db_coverage(self) -> dict[str, Any]:
        status = self._history_db.get_status()
        return {
            "initialized": status.initialized,
            "total_records": status.total_records,
            "date_range": {
                "earliest": status.earliest_date,
                "latest": status.latest_date,
            },
            "coverage": {
                "months": [month.to_dict() for month in status.coverage_months],
            },
        }

    async def get_db_history(
        self,
        *,
        item: str,
        cities: str | None = None,
        quality: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        granularity: str = "daily",
        include_latest_api: bool = False,
    ) -> dict[str, Any]:
        item_id, display_name = self.resolve_item(item)
        locations = self._parse_history_locations(cities)

        data = self.get_local_history(
            item_id=item_id,
            locations=locations,
            quality=quality,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
        )

        result = {
            "item": {
                "query": item,
                "id": item_id,
                "display_name": display_name,
            },
            "locations": locations,
            "quality": quality,
            "granularity": granularity,
            "date_range": {
                "start": start_date,
                "end": end_date,
            },
            "data": data,
            "record_count": len(data),
            "source": "local_duckdb",
        }

        if include_latest_api:
            latest_cities = locations or DEFAULT_LATEST_MARKET_CITIES
            result["latest_market"] = await self._fetch_latest_market_for_history(
                item_id=item_id,
                locations=latest_cities,
                quality=quality,
            )

        return result

    @staticmethod
    def _parse_history_locations(cities: str | list[str] | None) -> list[str] | None:
        if cities is None:
            return None
        if isinstance(cities, str):
            return [city.strip() for city in cities.split(",") if city.strip()]
        return [city.strip() for city in cities if city and city.strip()]

    @staticmethod
    def _cleanup_dump_files(download_dir: Any) -> list[str]:
        cleaned_dumps: list[str] = []
        download_dir.mkdir(parents=True, exist_ok=True)
        for path in download_dir.iterdir():
            if path.is_file():
                path.unlink()
                cleaned_dumps.append(path.name)
        return cleaned_dumps

    async def _fetch_latest_market_for_history(
        self,
        *,
        item_id: str,
        locations: list[str],
        quality: int | None,
    ) -> dict[str, Any]:
        try:
            return await self.get_market_prices(
                item=item_id,
                cities=locations,
                quality=quality,
                force_refresh=False,
            )
        except MarketServiceError as exc:
            return {
                "error": str(exc),
                "status_code": exc.status_code,
                "item": item_id,
                "locations": locations,
            }
        except Exception as exc:
            logger.warning("[MarketApplicationService] Failed latest API market fetch for %s: %s", item_id, exc)
            return {
                "error": str(exc),
                "status_code": 500,
                "item": item_id,
                "locations": locations,
            }
