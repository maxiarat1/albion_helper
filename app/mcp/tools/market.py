"""MCP tools for market and history data."""

from __future__ import annotations

import statistics
from typing import Any

from app.bootstrap import get_container
from app.mcp.registry import Param, tool
from app.mcp.tool_templates import (
    READ_ONLY_OPEN_WORLD,
    cities_param,
    end_date_param,
    item_param,
    quality_param,
    limit_param,
    start_date_param,
)

from ._resolve import attach_smart_resolution, resolve_item_smart

market_app = get_container().market
history_db = get_container().history_db

DEFAULT_CITIES = [
    "Caerleon",
    "Bridgewatch",
    "Martlock",
    "Thetford",
    "Fort Sterling",
    "Lymhurst",
    "Black Market",
    "Brecilien",
]

# Prices at or above this are almost certainly placeholder/troll listings.
_OUTLIER_CEILING = 995_999


def _summarize_prices(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a clean price summary by filtering outlier/placeholder listings.

    The AODP API returns raw marketplace data which often includes troll
    listings (e.g. 999999 silver sell orders, 1 silver buy orders).  This
    function computes a summary the LLM can rely on.

    When multiple quality levels are present for the same city, the lowest
    sell price and highest buy price per city are kept.
    """
    # Collect candidates keyed by location so we keep the best per city.
    sell_by_loc: dict[str, dict[str, Any]] = {}
    buy_by_loc: dict[str, dict[str, Any]] = {}

    for entry in data:
        loc = entry.get("location", "?")

        sell_min = entry.get("sell_price_min", 0)
        if sell_min and sell_min > 0:
            prev = sell_by_loc.get(loc)
            if prev is None or sell_min < prev["price"]:
                sell_by_loc[loc] = {"location": loc, "price": sell_min, "date": entry.get("sell_price_min_date")}

        buy_max = entry.get("buy_price_max", 0)
        if buy_max and buy_max > 0:
            prev = buy_by_loc.get(loc)
            if prev is None or buy_max > prev["price"]:
                buy_by_loc[loc] = {"location": loc, "price": buy_max, "date": entry.get("buy_price_max_date")}

    sell_entries = list(sell_by_loc.values())
    buy_entries = list(buy_by_loc.values())

    # Filter outliers using median-based detection
    clean_sells = _filter_outliers(sell_entries)
    clean_buys = _filter_outliers(buy_entries, high_outliers=False)

    summary: dict[str, Any] = {}

    if clean_sells:
        best = min(clean_sells, key=lambda e: e["price"])
        summary["best_sell"] = {"location": best["location"], "price": best["price"], "date": best["date"]}
        if len(clean_sells) > 1:
            summary["sell_prices"] = {e["location"]: e["price"] for e in clean_sells}
    else:
        summary["best_sell"] = None

    if clean_buys:
        best = max(clean_buys, key=lambda e: e["price"])
        summary["best_buy"] = {"location": best["location"], "price": best["price"], "date": best["date"]}
        if len(clean_buys) > 1:
            summary["buy_prices"] = {e["location"]: e["price"] for e in clean_buys}
    else:
        summary["best_buy"] = None

    return summary


def _filter_outliers(
    entries: list[dict[str, Any]],
    *,
    high_outliers: bool = True,
) -> list[dict[str, Any]]:
    """Remove outlier prices using two-pass median filtering.

    For sell prices (high_outliers=True):
      1. Remove anything >= absolute ceiling (obvious troll listings).
      2. Recompute median from survivors, remove anything > 5x that median.
    For buy prices (high_outliers=False):
      Remove anything < 0.2x median.
    """
    if not entries:
        return []

    if high_outliers:
        # Pass 1: remove obvious ceiling-level trolls
        survivors = [e for e in entries if e["price"] < _OUTLIER_CEILING]
        if not survivors:
            return []
        # Pass 2: median-based filter on remaining values
        med = statistics.median([e["price"] for e in survivors])
        threshold = max(med * 5, 1)
        return [e for e in survivors if e["price"] <= threshold]
    else:
        med = statistics.median([e["price"] for e in entries])
        threshold = med * 0.2
        return [e for e in entries if e["price"] >= threshold]


@tool(
    name="market_data",
    description=(
        "Unified market tool for both current prices and historical trends. "
        "Use mode='snapshot' for current buy/sell prices and mode='history' for time-series data."
    ),
    params=[
        item_param(
            required=True,
            description="Item name or ID. Accepts: display name, tier shorthand, or unique ID.",
        ),
        Param("mode", "string", "Query mode. Default: snapshot.", enum=["snapshot", "history"]),
        Param("source", "string", "Data source for mode='history'. Default: auto.", enum=["auto", "local", "live"]),
        cities_param(description="Cities to check. Defaults to all major cities."),
        quality_param(),
        start_date_param(),
        end_date_param(),
        Param("time_scale", "string", "Live history granularity. Default: hourly.", enum=["hourly", "daily"]),
        Param("granularity", "string", "Local history aggregation. Default: daily.", enum=["hourly", "daily", "weekly", "monthly"]),
        Param("raw", "boolean", "When mode='history' and source is local, return raw records. Default: false."),
        limit_param(description="Max local raw records. Default: 1000. Only applies when raw=true."),
    ],
    annotations=READ_ONLY_OPEN_WORLD,
)
async def market_data(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch snapshot or history market data through a single tool."""
    mode = args.get("mode", "snapshot")
    source = args.get("source", "auto")
    if mode == "history":
        return await _market_history(args, source=source)
    return await _market_snapshot(args)


async def _market_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    item_query = args["item"]
    item, resolution_note = resolve_item_smart(item_query)
    cities = args.get("cities", DEFAULT_CITIES)
    quality = args.get("quality")

    result = await market_app.get_market_prices(
        item=item,
        cities=cities,
        quality=quality,
        force_refresh=True,
    )

    summary = _summarize_prices(result.get("data", []))
    payload: dict[str, Any] = {
        "item": {"query": item_query, "id": item},
        "mode": "snapshot",
        "source": {"requested": "live", "resolved": "live_aodp_prices"},
        "locations": result.get("locations", cities),
        "quality": quality,
        "timeframe": {"start": None, "end": None, "time_scale": None, "granularity": None},
        "summary": summary,
        "data": result.get("data", []),
        "record_count": len(result.get("data", [])),
        "freshness": result.get("freshness"),
        "region": result.get("region"),
        "fetched_at": result.get("fetched_at"),
        "cached": result.get("cached", False),
    }
    return attach_smart_resolution(payload, resolution_note)


async def _market_history(
    args: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    item_query = args["item"]
    item, resolution_note = resolve_item_smart(item_query)
    cities = args.get("cities")
    quality = args.get("quality")
    start_date = args.get("start_date")
    end_date = args.get("end_date")
    time_scale = args.get("time_scale", "hourly")
    granularity = args.get("granularity", "daily")
    use_raw = args.get("raw", False)
    limit = args.get("limit", 1000)

    if source in {"auto", "local"}:
        local_status = history_db.get_status()
        if local_status.total_records > 0:
            local_data = _market_history_local_data(
                item_id=item,
                locations=cities,
                quality=quality,
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
                use_raw=use_raw,
                limit=limit,
            )
            if local_data or source == "local":
                local_payload = _market_history_payload(
                    item_query=item_query,
                    item_id=item,
                    locations=cities,
                    quality=quality,
                    start_date=start_date,
                    end_date=end_date,
                    time_scale=time_scale,
                    granularity=granularity,
                    use_raw=use_raw,
                    data=local_data,
                    source_requested=source,
                    source_resolved="local_duckdb",
                )
                return attach_smart_resolution(local_payload, resolution_note)
        elif source == "local":
            return attach_smart_resolution(
                {
                    "error": "No historical data available",
                    "hint": "Use db_update to download and import database dumps",
                    "item": {"query": item_query, "id": item},
                    "mode": "history",
                    "source": {"requested": "local", "resolved": "local_duckdb"},
                },
                resolution_note,
            )

    live_result = await market_app.get_live_history(
        item=item,
        cities=cities or DEFAULT_CITIES,
        quality=quality,
        time_scale=time_scale,
        start_date=start_date,
        end_date=end_date,
    )
    live_payload = _market_history_payload(
        item_query=item_query,
        item_id=item,
        locations=live_result.get("locations", cities),
        quality=quality,
        start_date=start_date,
        end_date=end_date,
        time_scale=time_scale,
        granularity=None,
        use_raw=False,
        data=live_result.get("data", []),
        source_requested=source,
        source_resolved="live_aodp_history",
    )
    live_payload["region"] = live_result.get("region")
    live_payload["fetched_at"] = live_result.get("fetched_at")
    return attach_smart_resolution(live_payload, resolution_note)


def _market_history_local_data(
    *,
    item_id: str,
    locations: list[str] | None,
    quality: int | None,
    start_date: str | None,
    end_date: str | None,
    granularity: str,
    use_raw: bool,
    limit: int,
) -> list[dict[str, Any]]:
    if use_raw:
        return market_app.query_local_history_raw(
            item_id=item_id,
            locations=locations,
            quality=quality,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    return market_app.get_local_history(
        item_id=item_id,
        locations=locations,
        quality=quality,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
    )


def _market_history_payload(
    *,
    item_query: str,
    item_id: str,
    locations: list[str] | None,
    quality: int | None,
    start_date: str | None,
    end_date: str | None,
    time_scale: str,
    granularity: str | None,
    use_raw: bool,
    data: list[dict[str, Any]],
    source_requested: str,
    source_resolved: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "item": {"query": item_query, "id": item_id},
        "mode": "history",
        "source": {"requested": source_requested, "resolved": source_resolved},
        "locations": locations,
        "quality": quality,
        "timeframe": {
            "start": start_date,
            "end": end_date,
            "time_scale": time_scale,
            "granularity": granularity,
        },
        "raw": use_raw,
        "summary": _summarize_history(data),
        "data": data,
        "record_count": len(data),
    }
    return payload


def _summarize_history(data: list[dict[str, Any]]) -> dict[str, Any]:
    if not data:
        return {"records": 0}

    def _first_present(entry: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            value = entry.get(key)
            if value is not None:
                return value
        return None

    sell_points: list[dict[str, Any]] = []
    buy_points: list[dict[str, Any]] = []
    primary_prices: list[float] = []
    timeline: list[str] = []
    locations: set[str] = set()

    for entry in data:
        ts = _first_present(entry, ["timestamp", "period"])
        if isinstance(ts, str) and ts:
            timeline.append(ts)
        location = entry.get("location")
        if isinstance(location, str) and location:
            locations.add(location)

        sell_price = _first_present(entry, ["avg_sell_min", "sell_price_min", "avg_price"])
        if isinstance(sell_price, (int, float)):
            primary_prices.append(float(sell_price))
            sell_points.append(
                {"price": float(sell_price), "location": location, "time": ts}
            )

        buy_price = _first_present(entry, ["avg_buy_max", "buy_price_max"])
        if isinstance(buy_price, (int, float)):
            buy_points.append(
                {"price": float(buy_price), "location": location, "time": ts}
            )

    summary: dict[str, Any] = {
        "records": len(data),
        "locations_count": len(locations),
    }
    if timeline:
        summary["latest_time"] = max(timeline)
        summary["earliest_time"] = min(timeline)
    if primary_prices:
        summary["price_min"] = int(min(primary_prices))
        summary["price_max"] = int(max(primary_prices))
        summary["price_median"] = int(statistics.median(primary_prices))
    if sell_points:
        best_sell = min(sell_points, key=lambda x: x["price"])
        summary["best_sell"] = {
            "price": int(best_sell["price"]),
            "location": best_sell["location"],
            "time": best_sell["time"],
        }
    if buy_points:
        best_buy = max(buy_points, key=lambda x: x["price"])
        summary["best_buy"] = {
            "price": int(best_buy["price"]),
            "location": best_buy["location"],
            "time": best_buy["time"],
        }
    return summary


@tool(
    name="gold_prices",
    description=(
        "Get the gold-to-silver exchange rate history. "
        "Returns price in silver per gold over time. "
        "Checks local database first, fetches from AODP API if needed."
    ),
    params=[
        Param("count", "integer", "Number of recent records to return (default 24).", minimum=1),
        start_date_param(),
        end_date_param(),
    ],
    annotations=READ_ONLY_OPEN_WORLD,
)
async def gold_prices(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch gold-to-silver exchange rate."""
    return await market_app.get_gold_prices(
        count=args.get("count"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
