"""System endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.llm.provider_factory import ProviderFactory

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
async def root() -> dict[str, str]:
    return {"service": "albion-helper-v2", "status": "ok", "version": "2.0"}


@router.get("/providers")
async def list_providers() -> dict[str, list[str]]:
    return {"providers": ProviderFactory.get_supported_providers()}
