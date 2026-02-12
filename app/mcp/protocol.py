"""Tool call parsing and formatting for MCP tool routing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


@dataclass(frozen=True)
class ToolCall:
    """Parsed tool call from LLM output."""

    tool: str | None
    arguments: dict[str, Any] = field(default_factory=dict)
    raw: str = ""

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool)


def extract_tool_call(text: str) -> ToolCall:
    """Extract a tool call from LLM output.

    Specifically looks for JSON objects containing a ``"tool"`` key,
    ignoring echoed results or other JSON the model may have emitted.
    Returns ToolCall(tool=None) if no tool call is found.
    """
    payload = _extract_tool_json(text)
    if payload is None:
        return ToolCall(tool=None, raw=text)

    tool = payload.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        return ToolCall(tool=None, raw=text)

    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        logger.warning("Tool call has non-object 'arguments': %r", args)
        args = {}

    return ToolCall(tool=tool.strip(), arguments=args, raw=text)


def format_tool_result(tool_name: str, result: Any, *, success: bool = True) -> str:
    """Format a tool result for injection into conversation context."""
    if success:
        if isinstance(result, dict):
            if tool_name == "execute_code":
                result = {
                    k: result.get(k)
                    for k in ("success", "result", "result_type", "output", "error", "observation")
                }
            elif tool_name == "market_data":
                # Strip raw data array — summary carries the distilled answer.
                result = {k: v for k, v in result.items() if k != "data"}
        result_str = json.dumps(result, indent=2) if isinstance(result, dict) else str(result)
        return f"\u2713 {tool_name}:\n{result_str}"
    return f"\u2717 {tool_name} failed: {result}"


def _is_tool_dict(obj: Any) -> bool:
    """Return True if *obj* is a dict with a non-empty string ``"tool"`` key."""
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("tool"), str)
        and bool(obj["tool"].strip())
    )


def _extract_tool_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object that has a ``"tool"`` key.

    Scans fenced code blocks first, then raw text.  JSON dicts that lack a
    ``"tool"`` key (e.g. echoed API results) are skipped so they can't
    shadow the real tool call.
    """
    stripped = text.strip()

    # 1. Check fenced ```json blocks (models often wrap calls in these)
    for fence in _FENCE_RE.finditer(stripped):
        try:
            parsed = json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            continue
        if _is_tool_dict(parsed):
            return parsed

    # 2. Try the whole text as a single JSON object
    try:
        parsed = json.loads(stripped)
        if _is_tool_dict(parsed):
            return parsed
    except json.JSONDecodeError:
        pass

    # 3. Scan for inline JSON objects with a "tool" key
    decoder = json.JSONDecoder()
    for idx, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[idx:])
        except json.JSONDecodeError:
            continue
        if _is_tool_dict(parsed):
            return parsed

    return None
