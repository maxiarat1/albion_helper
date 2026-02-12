"""Item metadata endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.bootstrap import get_container

router = APIRouter()


@router.get("/items/labels")
async def get_item_labels(ids: str) -> dict[str, Any]:
    try:
        return get_container().item_labels.get_labels(ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
