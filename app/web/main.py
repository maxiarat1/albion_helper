"""HTTP application entrypoint (composition-only)."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.application import ChatMessage, ChatRequest
from app.bootstrap import get_container
from app.llm.provider_factory import ProviderFactory
from app.mcp.router import mcp_router
from app.web.routers import (
    chat_router,
    database_router,
    items_router,
    market_router,
    system_router,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

container = get_container()

_cors_origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app = FastAPI(title="Albion Helper V3")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(items_router)
app.include_router(market_router)
app.include_router(chat_router)
app.include_router(database_router)
app.include_router(mcp_router, prefix="/mcp")

__all__ = [
    "app",
    "ProviderFactory",
    "ChatMessage",
    "ChatRequest",
]
