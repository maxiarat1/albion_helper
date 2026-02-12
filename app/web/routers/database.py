"""Historical database management endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.bootstrap import get_container

logger = logging.getLogger(__name__)

router = APIRouter()


class DbUpdateRequest(BaseModel):
    max_dumps: int = Field(default=1, description="Maximum dumps to process")


class DbResetRequest(BaseModel):
    cleanup_dumps: bool = Field(
        default=True,
        description="Whether to remove downloaded dump files after reset",
    )


@router.get("/db/status")
async def get_db_status(check_updates: bool = False) -> dict[str, Any]:
    return await get_container().market.get_db_status(check_updates=check_updates)


@router.post("/db/update")
async def trigger_db_update(request: DbUpdateRequest | None = None) -> dict[str, Any]:
    req = request or DbUpdateRequest()
    try:
        return await get_container().market.update_db(max_dumps=req.max_dumps)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error in trigger_db_update")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/db/update/start")
async def start_db_update(request: DbUpdateRequest | None = None) -> dict[str, Any]:
    req = request or DbUpdateRequest()
    try:
        return get_container().market.start_db_update(max_dumps=req.max_dumps)
    except Exception as exc:
        logger.exception("Error in start_db_update")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/db/update/progress")
async def get_db_update_progress() -> dict[str, Any]:
    return get_container().market.get_db_update_progress()


@router.post("/db/update/progress/clear")
async def clear_db_update_progress() -> dict[str, Any]:
    try:
        return get_container().market.clear_db_update_progress()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error in clear_db_update_progress")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/db/reset")
async def reset_database(request: DbResetRequest | None = None) -> dict[str, Any]:
    req = request or DbResetRequest()
    try:
        return get_container().market.reset_db(cleanup_dumps=req.cleanup_dumps)
    except Exception as exc:
        logger.exception("Error in reset_database")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/db/history")
async def get_db_history(
    item: str,
    cities: str | None = None,
    quality: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    granularity: str = "daily",
    include_latest_api: bool = False,
) -> dict[str, Any]:
    try:
        return await get_container().market.get_db_history(
            item=item,
            cities=cities,
            quality=quality,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            include_latest_api=include_latest_api,
        )
    except Exception as exc:
        logger.exception("Error in get_db_history")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/db/coverage")
async def get_db_coverage() -> dict[str, Any]:
    return get_container().market.get_db_coverage()
