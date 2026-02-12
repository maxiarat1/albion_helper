"""Market endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.bootstrap import get_container
from app.data import MarketServiceError

router = APIRouter()


@router.get("/market/prices")
async def get_market_prices(
    item: str,
    city: str,
    quality: int | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    try:
        return await get_container().market.get_market_prices(
            item=item,
            cities=[city],
            quality=quality,
            force_refresh=force_refresh,
        )
    except MarketServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/market/gold")
async def get_gold_prices(
    count: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    try:
        return await get_container().market.get_gold_prices(
            count=count,
            start_date=start_date,
            end_date=end_date,
        )
    except MarketServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
