"""FastAPI router for MCP tool listing and invocation.

Follows Model Context Protocol specification:
https://modelcontextprotocol.io/docs/concepts/tools
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.data import MarketServiceError
from .registry import registry, ToolResult
from . import tools  # noqa: F401

logger = logging.getLogger(__name__)

mcp_router = APIRouter()
_ALLOW_ADMIN_TOOLS = os.getenv("MCP_ALLOW_ADMIN_TOOLS", "false").strip().lower() == "true"


class ToolsListRequest(BaseModel):
    """MCP tools/list request."""

    cursor: str | None = Field(default=None, description="Pagination cursor (not implemented)")
    include_admin: bool = Field(default=False, alias="includeAdmin", description="Include admin-only tools when server allows it")


class ToolsListResponse(BaseModel):
    """MCP tools/list response."""

    tools: list[dict[str, Any]] = Field(..., description="Available tools")
    next_cursor: str | None = Field(default=None, alias="nextCursor")


class ToolCallRequest(BaseModel):
    """MCP tools/call request."""

    name: str = Field(..., description="Tool name to invoke")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class ToolCallResponse(BaseModel):
    """MCP tools/call response."""

    model_config = {"populate_by_name": True, "by_alias": True}

    content: list[dict[str, Any]] = Field(..., description="Result content blocks")
    is_error: bool = Field(default=False, alias="isError", description="Whether an error occurred")
    structured_content: Any | None = Field(
        default=None,
        alias="structuredContent",
        description="Optional structured result matching the tool output schema.",
    )


def _tool_error_response(message: str) -> ToolCallResponse:
    return ToolCallResponse(
        content=[{"type": "text", "text": message}],
        is_error=True,
    )


def _should_include_admin_tools(request: ToolsListRequest | None) -> bool:
    return bool(request and request.include_admin and _ALLOW_ADMIN_TOOLS)


@mcp_router.post("/tools/list")
async def list_tools(request: ToolsListRequest | None = None) -> ToolsListResponse:
    """MCP-compliant: List available tools.

    Endpoint: POST /mcp/tools/list
    """
    include_admin = _should_include_admin_tools(request)
    return ToolsListResponse(tools=registry.list_tools(include_admin=include_admin), next_cursor=None)


@mcp_router.post("/tools/call")
async def call_tool(payload: ToolCallRequest) -> ToolCallResponse:
    """MCP-compliant: Invoke a tool by name.

    Endpoint: POST /mcp/tools/call

    Returns content blocks per MCP spec:
    - Success: { content: [{ type: "text", text: "..." }], isError: false }
    - Error: { content: [{ type: "text", text: "error message" }], isError: true }
    """
    tool_name = payload.name
    tool_args = payload.arguments
    tool = registry.get(tool_name, include_admin=_ALLOW_ADMIN_TOOLS)
    if not tool:
        return _tool_error_response(f"Tool not found: {tool_name}")

    try:
        registry.validate(tool.input_schema, tool_args)
        result = await tool.handler(tool_args)
        mcp_result = result if isinstance(result, ToolResult) else ToolResult.json(result)
        return ToolCallResponse(**mcp_result.to_mcp_format())
    except MarketServiceError as exc:
        logger.warning("Market service error in tool %s: %s", tool_name, exc)
        return _tool_error_response(str(exc))
    except ValueError as exc:
        logger.warning("Validation error in tool %s: %s", tool_name, exc)
        return _tool_error_response(f"Invalid arguments: {exc}")
    except Exception as exc:
        logger.exception("Unexpected error in tool %s", tool_name)
        return _tool_error_response(f"Tool execution failed: {type(exc).__name__}")
