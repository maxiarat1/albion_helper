"""MCP tools for local historical database maintenance."""

from __future__ import annotations

import logging
from typing import Any

from app.bootstrap import get_container
from app.mcp.registry import Param, tool
from app.mcp.tool_templates import (
    MUTATING_LOCAL,
    READ_ONLY_LOCAL,
)

logger = logging.getLogger(__name__)
market_app = get_container().market


@tool(
    name="db_status",
    description="Get local database status: record counts, date ranges, monthly coverage, and optionally check for available updates.",
    params=[
        Param("check_updates", "boolean", "Check AODP for new dumps. Default: false."),
    ],
    annotations=READ_ONLY_LOCAL,
)
async def db_status(args: dict[str, Any]) -> dict[str, Any]:
    """Get database status and coverage, optionally check for updates."""
    status = get_container().history_db.get_status()

    result: dict[str, Any] = {
        "initialized": status.initialized,
        "total_records": status.total_records,
        "date_range": {
            "earliest": status.earliest_date,
            "latest": status.latest_date,
        },
        "coverage": {
            "months": [m.to_dict() for m in status.coverage_months],
        },
        "imported_dumps": status.imported_dumps,
        "source": "local_duckdb",
    }

    if args.get("check_updates", False):
        try:
            updates = await market_app.get_db_updates()
            result["updates_available"] = {
                "total_available": updates["total_available"],
                "daily_available": updates["daily_available"],
                "pending_import": updates["pending_import"],
                "pending_dumps": [d["name"] for d in updates["pending_dumps"][:5]],
                "strategy": updates["strategy"],
            }
        except Exception as e:
            logger.warning("Failed to check for updates: %s", e)
            result["updates_available"] = {"error": str(e)}

    return result


@tool(
    name="db_update",
    description="Download and import new database dumps from AODP. Use db_status with check_updates=true first.",
    params=[
        Param("max_dumps", "integer", "Max dumps to process. Default: 1.", minimum=1),
    ],
    annotations=MUTATING_LOCAL,
    visibility="admin",
)
async def db_update(args: dict[str, Any]) -> dict[str, Any]:
    """Download and import new database dumps."""
    max_dumps = args.get("max_dumps", 1)
    return await market_app.update_db(max_dumps=max_dumps)
