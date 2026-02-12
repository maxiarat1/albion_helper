"""Chat endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.application import ChatRequest
from app.bootstrap import get_container

router = APIRouter()


@router.get("/ollama/models")
async def list_ollama_models() -> dict[str, Any]:
    return await get_container().chat.list_ollama_models()


@router.post("/chat")
async def chat(request: ChatRequest) -> Any:
    return await get_container().chat.chat(request)
