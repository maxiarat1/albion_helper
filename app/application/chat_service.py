"""Application service for chat orchestration and tool routing."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.data import MarketServiceError
from app.llm.base_provider import Message
from app.llm.provider_factory import ProviderFactory
from app.mcp.protocol import extract_tool_call, format_tool_result
from app.mcp.registry import registry
from app.observability import LangfuseTracer
from app.prompts import default_assembler

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 15
_REASONING_EFFORTS = {"low", "medium", "high"}
_DEFAULT_ANTHROPIC_THINKING_BUDGET = 2048
_DEFAULT_ANTHROPIC_THINKING_OUTPUT_RESERVE = 512
_EMPTY_THINKING_INFO = {
    "supported": False,
    "mode_type": "unknown",
    "modes": [],
    "source": "unknown",
}
_PRICE_INTENT_RE = re.compile(r"\b(price|cost|value|worth)\b", re.IGNORECASE)
_CANONICAL_ITEM_ID_RE = re.compile(r"\bT[1-8](?:_[A-Z0-9]+)+(?:@\d+)?\b", re.IGNORECASE)
_TIER_ITEM_HINT_RE = re.compile(r"\bT[1-8](?:[.@][0-4])?\b", re.IGNORECASE)
_PRICE_ITEM_PATTERNS = (
    re.compile(r"^\s*how much is(?: the)?\s+(?P<item>.+?)\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*what(?:'s| is)?(?: the)?(?: current| latest)?(?: market)?"
        r"\s+(?:price|cost|value|worth)\s+(?:of|for)\s+(?P<item>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:price|cost|value|worth)\s+(?:of|for)?\s*(?P<item>.+?)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?P<item>.+?)\s+(?:price|cost|value|worth)\s*$", re.IGNORECASE),
)


class ChatMessage(BaseModel):
    """Chat message schema."""

    role: str = Field(..., description="Message role (user, assistant, system)")
    content: str = Field(..., description="Message content")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid_roles = {"user", "assistant", "system"}
        if v not in valid_roles:
            raise ValueError(f"Role must be one of {valid_roles}")
        return v

    def to_message(self) -> Message:
        return Message(role=self.role, content=self.content)


class ChatRequest(BaseModel):
    """Chat request schema with validation."""

    provider: str = Field(..., description="LLM provider name")
    model: str = Field(..., description="Model name")
    messages: list[ChatMessage] = Field(..., description="Conversation messages")
    stream: bool = Field(default=False, description="Enable streaming")
    api_key: str | None = Field(default=None, description="Provider API key")
    options: dict[str, Any] | None = Field(default=None, description="Provider-specific options")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        supported = ProviderFactory.get_supported_providers()
        if v.lower() not in supported:
            raise ValueError(f"Provider must be one of {supported}")
        return v.lower()


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _extract_delta_anthropic(chunk: dict[str, Any]) -> str:
    if chunk.get("event") != "content_block_delta":
        return ""
    data = chunk.get("data") or {}
    return (data.get("delta") or {}).get("text") or ""


def _extract_delta_ollama(chunk: dict[str, Any]) -> str:
    return (chunk.get("message") or {}).get("content") or ""


def _extract_text_anthropic(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in response.get("content", []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
            continue
        if block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


def _extract_text(provider: str, response: dict[str, Any]) -> str:
    if provider == "anthropic":
        return _extract_text_anthropic(response)
    if provider == "ollama":
        return ((response.get("message") or {}).get("content") or "").strip()
    if provider == "openai":
        return (response.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    if provider == "gemini":
        parts = response.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        if parts:
            return (parts[0].get("text") or "").strip()
    return ""


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_usage_details(provider: str, response: dict[str, Any]) -> dict[str, int] | None:
    if provider == "openai":
        usage = response.get("usage") or {}
        input_tokens = _to_int(usage.get("prompt_tokens"))
        output_tokens = _to_int(usage.get("completion_tokens"))
        total_tokens = _to_int(usage.get("total_tokens"))
    elif provider == "anthropic":
        usage = response.get("usage") or {}
        input_tokens = _to_int(usage.get("input_tokens"))
        output_tokens = _to_int(usage.get("output_tokens"))
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
    elif provider == "gemini":
        usage = response.get("usageMetadata") or {}
        input_tokens = _to_int(usage.get("promptTokenCount"))
        output_tokens = _to_int(usage.get("candidatesTokenCount"))
        total_tokens = _to_int(usage.get("totalTokenCount"))
    elif provider == "ollama":
        input_tokens = _to_int(response.get("prompt_eval_count"))
        output_tokens = _to_int(response.get("eval_count"))
        total_tokens = None
        if input_tokens is not None or output_tokens is not None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
    else:
        return None

    usage_details: dict[str, int] = {}
    if input_tokens is not None:
        usage_details["input"] = input_tokens
    if output_tokens is not None:
        usage_details["output"] = output_tokens
    if total_tokens is not None:
        usage_details["total"] = total_tokens
    return usage_details or None


def _messages_to_trace_payload(messages: list[Message]) -> list[dict[str, str]]:
    return [message.to_dict() for message in messages]


def _parse_langfuse_options(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _build_langfuse_request_metadata(
    *,
    request: ChatRequest,
    mcp_enabled: bool,
    reasoning_config: dict[str, Any],
    langfuse_options: dict[str, Any],
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "provider": request.provider,
        "model": request.model,
        "stream": request.stream,
        "message_count": len(request.messages),
        "mcp_enabled": mcp_enabled,
        "reasoning_enabled": bool(reasoning_config.get("enabled")),
    }

    user_id = langfuse_options.get("user_id")
    session_id = langfuse_options.get("session_id")
    tags = langfuse_options.get("tags")
    if user_id is not None:
        metadata["user_id"] = str(user_id)
    if session_id is not None:
        metadata["session_id"] = str(session_id)
    if isinstance(tags, list):
        metadata["tags"] = [str(tag) for tag in tags]

    custom_metadata = langfuse_options.get("metadata")
    if isinstance(custom_metadata, dict):
        metadata.update(custom_metadata)

    return metadata


def _normalize_ollama_model_name(value: str) -> str:
    return str(value or "").strip()


def _ollama_model_key(model_name: str) -> str:
    return _normalize_ollama_model_name(model_name).split(":", 1)[0].lower()


def _guess_ollama_thinking_mode_type(model_name: str) -> str | None:
    key = _ollama_model_key(model_name)
    if "gpt-oss" in key:
        return "levels"
    if any(token in key for token in ("qwen3", "deepseek-r1", "deepseek-v3.1")):
        return "boolean"
    return None


def _ollama_thinking_modes_for_type(mode_type: str | None) -> list[str]:
    if mode_type == "levels":
        return ["low", "medium", "high"]
    return []


def _resolve_ollama_thinking_option(
    *,
    model_name: str,
    explicit: Any = None,
) -> bool | str:
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, str):
        normalized = explicit.strip().lower()
        if normalized in _REASONING_EFFORTS:
            return normalized
        if normalized in {"true", "on", "enabled", "yes"}:
            return True
        if normalized in {"false", "off", "disabled", "no"}:
            return False

    guessed = _guess_ollama_thinking_mode_type(model_name)
    if guessed == "levels":
        return "medium"
    return True


async def _ollama_model_thinking_info(provider: Any, model_name: str) -> dict[str, Any]:
    model_name = _normalize_ollama_model_name(model_name)
    info: dict[str, Any] = {
        "supported": False,
        "mode_type": "unknown",
        "modes": [],
        "source": "unknown",
    }

    capabilities: list[str] = []
    show_model = getattr(provider, "show_model", None)
    if callable(show_model):
        try:
            details = await show_model(model_name)
            caps = details.get("capabilities")
            if isinstance(caps, list):
                capabilities = [str(cap).strip().lower() for cap in caps if str(cap).strip()]
        except Exception:
            capabilities = []

    if capabilities:
        supports_thinking = "thinking" in capabilities
        info["supported"] = supports_thinking
        info["source"] = "show_capabilities"
        if supports_thinking:
            mode_type = _guess_ollama_thinking_mode_type(model_name) or "boolean"
            info["mode_type"] = mode_type
            info["modes"] = _ollama_thinking_modes_for_type(mode_type)
        return info

    guessed = _guess_ollama_thinking_mode_type(model_name)
    if guessed:
        info["supported"] = True
        info["mode_type"] = guessed
        info["modes"] = _ollama_thinking_modes_for_type(guessed)
        info["source"] = "heuristic"
        return info

    info["source"] = "heuristic"
    return info


def _allowed_tools(mcp_config: dict[str, Any]) -> set[str]:
    tools = {tool["name"] for tool in registry.list_tools()}
    allowed = set(mcp_config.get("allowed_tools") or tools)
    disabled = set(mcp_config.get("disabled_tools") or [])
    return (allowed & tools) - disabled


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(numeric, maximum))


def _parse_reasoning_config(raw: Any) -> dict[str, Any]:
    config = raw if isinstance(raw, dict) else {}
    enabled = bool(config.get("enabled"))
    effort = str(config.get("effort", "medium")).strip().lower()
    if effort not in _REASONING_EFFORTS:
        effort = "medium"

    return {
        "enabled": enabled,
        "effort": effort,
        "provider_native": bool(config.get("provider_native", True)) if enabled else False,
        "anthropic_budget_tokens": _clamp_int(
            config.get("anthropic_budget_tokens", config.get("budget_tokens", _DEFAULT_ANTHROPIC_THINKING_BUDGET)),
            default=_DEFAULT_ANTHROPIC_THINKING_BUDGET,
            minimum=1024,
            maximum=32_000,
        ),
        "anthropic_output_reserve_tokens": _clamp_int(
            config.get("anthropic_output_reserve_tokens", _DEFAULT_ANTHROPIC_THINKING_OUTPUT_RESERVE),
            default=_DEFAULT_ANTHROPIC_THINKING_OUTPUT_RESERVE,
            minimum=64,
            maximum=4096,
        ),
        "ollama_think": config.get("ollama_think"),
    }


def _apply_provider_reasoning_options(
    *,
    provider_name: str,
    model: str,
    kwargs: dict[str, Any],
    reasoning_config: dict[str, Any],
) -> None:
    if not reasoning_config.get("enabled") or not reasoning_config.get("provider_native"):
        return

    if provider_name == "anthropic":
        budget_tokens = int(reasoning_config["anthropic_budget_tokens"])
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}

        reserve = int(reasoning_config["anthropic_output_reserve_tokens"])
        required_tokens = budget_tokens + reserve
        current_max_tokens = _clamp_int(
            kwargs.get("max_tokens", required_tokens),
            default=required_tokens,
            minimum=1,
            maximum=1_000_000,
        )
        if current_max_tokens < required_tokens:
            kwargs["max_tokens"] = required_tokens
        return

    if provider_name == "openai":
        kwargs["reasoning_effort"] = reasoning_config["effort"]
        return

    if provider_name == "ollama":
        kwargs["think"] = _resolve_ollama_thinking_option(
            model_name=model,
            explicit=reasoning_config.get("ollama_think"),
        )


def _canonicalize_tool_name(tool_name: str, allowed: set[str]) -> str:
    raw = (tool_name or "").strip()
    if not raw:
        raise ValueError("Tool is disabled or unknown")

    normalized_candidates: list[str] = []
    lowered = raw.lower()
    dash_norm = lowered.replace("-", "_")
    space_norm = dash_norm.replace(" ", "_")
    for candidate in (raw, lowered, dash_norm, space_norm):
        if candidate not in normalized_candidates:
            normalized_candidates.append(candidate)

    for candidate in normalized_candidates:
        if candidate in allowed:
            return candidate

    lower_lookup = {name.lower(): name for name in allowed}
    for candidate in normalized_candidates:
        mapped = lower_lookup.get(candidate.lower())
        if mapped:
            return mapped

    raise ValueError(
        f"Tool '{tool_name}' is disabled or unknown. Allowed tools: {sorted(allowed)}"
    )


async def _execute_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    if tool_name not in allowed:
        raise ValueError(
            f"Tool '{tool_name}' is disabled or unknown. Allowed tools: {sorted(allowed)}"
        )
    tool = registry.get(tool_name)
    if not tool:
        raise ValueError(f"Tool not found: {tool_name}")
    registry.validate(tool.input_schema, arguments)
    return await tool.handler(arguments)


def _tool_activity_entry(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    success: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": "tool_call",
        "tool": tool_name,
        "arguments": arguments,
        "success": success,
    }
    if success and result is not None:
        entry["result"] = result
    if not success and error:
        entry["error"] = error
    return entry


def _tool_call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    try:
        normalized_args = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        normalized_args = repr(arguments)
    return f"{tool_name}:{normalized_args}"


def _record_tool_result(
    *,
    tool_activity: list[dict[str, Any]],
    tool_context: list[Message],
    tool_name: str,
    arguments: dict[str, Any],
    result: Any,
    success: bool,
) -> None:
    if success:
        tool_activity.append(
            _tool_activity_entry(
                tool_name=tool_name,
                arguments=arguments,
                success=True,
                result=result,
            )
        )
    else:
        tool_activity.append(
            _tool_activity_entry(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=str(result),
            )
        )

    tool_context.append(
        Message(
            role="system",
            content=format_tool_result(tool_name, result, success=success),
        )
    )


@dataclass
class ToolLoopResult:
    """Result of _run_tool_loop with full debug trace."""

    tool_activity: list[dict[str, Any]]
    tool_context: list[Message]
    response_text: str | None
    rounds: list[dict[str, Any]]


def _round_messages(all_messages: list[Message], iteration: int) -> list[dict[str, str]]:
    """Serialize messages for a debug round.

    The system prompt is included verbatim on round 1 and replaced with a
    length placeholder on subsequent rounds to keep the payload compact.
    """
    out: list[dict[str, str]] = []
    for msg in all_messages:
        if msg.role == "system" and iteration > 0 and len(msg.content) > 300:
            out.append({"role": msg.role, "content": f"[{len(msg.content)} chars]"})
        else:
            out.append(msg.to_dict())
    return out


async def _run_tool_loop(
    *,
    provider: Any,
    provider_name: str,
    model: str,
    kwargs: dict[str, Any],
    system_prompt: Message,
    messages: list[Message],
    allowed: set[str],
    direct_tool_call: dict[str, Any] | None = None,
) -> ToolLoopResult:
    """Run the unified tool loop.

    Each iteration makes a single LLM call. The model either responds with
    a tool-call JSON (execute and loop) or plain text (final answer).

    The model's own output is preserved as assistant messages in tool_context
    so it can see its prior actions on subsequent iterations. This gives
    each iteration the full conversational history:
        [system_prompt, *user_messages, assistant_call_1, tool_result_1, ...]
    """
    tool_activity: list[dict[str, Any]] = []
    tool_context: list[Message] = []
    rounds: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    duplicate_reported: set[str] = set()
    forced_price_fallback_used = False

    # Direct tool call (tool_only mode) — execute without LLM routing
    if direct_tool_call:
        tool_name = _canonicalize_tool_name(str(direct_tool_call.get("name", "")), allowed)
        tool_args = direct_tool_call.get("arguments") or {}
        tool_result = await _execute_tool_call(tool_name, tool_args, allowed)
        _record_tool_result(
            tool_activity=tool_activity,
            tool_context=tool_context,
            tool_name=tool_name,
            arguments=tool_args,
            result=tool_result,
            success=True,
        )
        return ToolLoopResult(tool_activity, tool_context, None, rounds)

    for iteration in range(MAX_TOOL_CALLS):
        all_messages = [system_prompt, *messages, *tool_context]

        try:
            response = await provider.chat(all_messages, model=model, **kwargs)
        except Exception as exc:
            logger.warning("[API] Tool loop iteration %d failed: %s", iteration + 1, exc)
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": None,
                "outcome": "api_error",
                "error": str(exc),
            })
            break

        text = _extract_text(provider_name, response)
        call = extract_tool_call(text)

        if not call.wants_tool:
            fallback_call = None
            if not forced_price_fallback_used and not tool_activity:
                fallback_call = _fallback_price_tool_call(messages=messages, allowed=allowed)
            if fallback_call:
                forced_price_fallback_used = True
                # Preserve the model's text so it sees its own output on the next iteration
                tool_context.append(Message(role="assistant", content=text))
                tool_name = fallback_call["name"]
                tool_args = fallback_call["arguments"]
                signature = _tool_call_signature(tool_name, tool_args)
                seen_signatures.add(signature)
                logger.info("[API] Tool loop fallback: forcing %r for price intent", tool_name)
                try:
                    tool_result = await _execute_tool_call(tool_name, tool_args, allowed)
                    _record_tool_result(
                        tool_activity=tool_activity,
                        tool_context=tool_context,
                        tool_name=tool_name,
                        arguments=tool_args,
                        result=tool_result,
                        success=True,
                    )
                    rounds.append({
                        "iteration": iteration + 1,
                        "messages": _round_messages(all_messages, iteration),
                        "response": text,
                        "outcome": "fallback",
                        "tool": tool_name,
                        "arguments": tool_args,
                    })
                except Exception as exc:
                    logger.warning("[API] Fallback tool %s failed: %s", tool_name, exc)
                    _record_tool_result(
                        tool_activity=tool_activity,
                        tool_context=tool_context,
                        tool_name=tool_name,
                        arguments=tool_args,
                        result=str(exc),
                        success=False,
                    )
                    rounds.append({
                        "iteration": iteration + 1,
                        "messages": _round_messages(all_messages, iteration),
                        "response": text,
                        "outcome": "fallback_error",
                        "tool": tool_name,
                        "arguments": tool_args,
                        "error": str(exc),
                    })
                continue
            # Model responded with text — this is the final answer
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": text,
                "outcome": "final_answer",
            })
            return ToolLoopResult(tool_activity, tool_context, text, rounds)

        # Preserve the model's tool-call output as an assistant turn so it
        # sees its own prior actions on subsequent iterations.
        tool_context.append(Message(role="assistant", content=text))

        # Validate tool name
        try:
            tool_name = _canonicalize_tool_name(call.tool, allowed)
        except ValueError:
            logger.warning("[API] Tool loop: unknown tool %r", call.tool)
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": text,
                "outcome": "unknown_tool",
                "tool": call.tool,
            })
            return ToolLoopResult(tool_activity, tool_context, text, rounds)

        tool_args = call.arguments
        signature = _tool_call_signature(tool_name, tool_args)

        # Duplicate detection (2-level)
        if signature in seen_signatures:
            if signature in duplicate_reported:
                logger.info("[API] Tool loop: repeated dup for %r, ending", tool_name)
                rounds.append({
                    "iteration": iteration + 1,
                    "messages": _round_messages(all_messages, iteration),
                    "response": text,
                    "outcome": "duplicate_halt",
                    "tool": tool_name,
                    "arguments": tool_args,
                })
                break
            duplicate_reported.add(signature)
            logger.info("[API] Tool loop iteration %d: dup blocked for %r", iteration + 1, tool_name)
            _record_tool_result(
                tool_activity=tool_activity,
                tool_context=tool_context,
                tool_name=tool_name,
                arguments=tool_args,
                result="Duplicate tool call blocked: this exact call already ran. Use prior results or respond.",
                success=False,
            )
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": text,
                "outcome": "duplicate_blocked",
                "tool": tool_name,
                "arguments": tool_args,
            })
            continue
        seen_signatures.add(signature)

        # Execute
        logger.info("[API] Tool loop iteration %d: calling %r", iteration + 1, tool_name)
        try:
            tool_result = await _execute_tool_call(tool_name, tool_args, allowed)
            _record_tool_result(
                tool_activity=tool_activity,
                tool_context=tool_context,
                tool_name=tool_name,
                arguments=tool_args,
                result=tool_result,
                success=True,
            )
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": text,
                "outcome": "tool_call",
                "tool": tool_name,
                "arguments": tool_args,
            })
        except Exception as exc:
            logger.warning("[API] Tool %s failed: %s", tool_name, exc)
            _record_tool_result(
                tool_activity=tool_activity,
                tool_context=tool_context,
                tool_name=tool_name,
                arguments=tool_args,
                result=str(exc),
                success=False,
            )
            rounds.append({
                "iteration": iteration + 1,
                "messages": _round_messages(all_messages, iteration),
                "response": text,
                "outcome": "tool_error",
                "tool": tool_name,
                "arguments": tool_args,
                "error": str(exc),
            })

    return ToolLoopResult(tool_activity, tool_context, None, rounds)


def _build_provider_kwargs(
    *,
    provider_name: str,
    model: str,
    options: dict[str, Any],
    max_tokens: int | None,
    reasoning_config: dict[str, Any],
) -> dict[str, Any]:
    kwargs = dict(options)
    if provider_name == "anthropic" and max_tokens:
        kwargs["max_tokens"] = max_tokens
    _apply_provider_reasoning_options(
        provider_name=provider_name,
        model=model,
        kwargs=kwargs,
        reasoning_config=reasoning_config,
    )
    return kwargs


def _build_response_meta(
    *,
    tool_activity: list[dict[str, Any]],
    rounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if tool_activity:
        meta["tool_calls"] = tool_activity
    if rounds:
        meta["rounds"] = rounds
    return meta


def _tool_preamble(tool_activity: list[dict[str, Any]]) -> str:
    """Build a short tool-usage annotation to prepend to assistant responses.

    When this annotated text later appears in conversation history, the model
    sees that tools were used in the previous turn (rather than the answer
    being fabricated from memory).  This prevents the pattern where the model
    mimics a tool-free answer on the next turn.

    Returns an empty string when no tools were called.
    """
    if not tool_activity:
        return ""
    names: list[str] = []
    for entry in tool_activity:
        name = entry.get("tool") or entry.get("name") or ""
        if name and name not in names:
            names.append(name)
    n = len(tool_activity)
    label = ", ".join(names)
    return f"[Used tools: {label} ({n} call{'s' if n != 1 else ''})]\n"


def _extract_stream_delta(provider_name: str, chunk: dict[str, Any]) -> str:
    if provider_name == "anthropic":
        return _extract_delta_anthropic(chunk)
    if provider_name == "ollama":
        return _extract_delta_ollama(chunk)
    return ""


def _latest_user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content or ""
    return ""


def _extract_price_item_query(user_text: str) -> str | None:
    text = (user_text or "").strip().strip("`")
    if not text:
        return None

    canonical = _CANONICAL_ITEM_ID_RE.search(text)
    if canonical:
        return canonical.group(0).upper()

    candidate = text.rstrip("?.!,;: ")
    for pattern in _PRICE_ITEM_PATTERNS:
        match = pattern.match(candidate)
        if match:
            candidate = match.group("item").strip()
            break

    candidate = candidate.strip("`'\" ").rstrip("?.!,;: ")
    if not candidate:
        return None
    if len(candidate) > 120:
        return None
    if not (_TIER_ITEM_HINT_RE.search(candidate) or _CANONICAL_ITEM_ID_RE.search(candidate)):
        return None
    return candidate


def _fallback_price_tool_call(
    *,
    messages: list[Message],
    allowed: set[str],
) -> dict[str, Any] | None:
    if "market_data" not in allowed:
        return None
    user_text = _latest_user_text(messages)
    if not user_text or not _PRICE_INTENT_RE.search(user_text):
        return None
    item_query = _extract_price_item_query(user_text)
    if not item_query:
        return None
    return {
        "name": "market_data",
        "arguments": {"item": item_query, "mode": "snapshot"},
    }


def _build_system_prompt(allowed_tools: set[str]) -> Message:
    all_tools = registry.list_tools()
    tools = [t for t in all_tools if t["name"] in allowed_tools] if allowed_tools else all_tools

    assembled = default_assembler.assemble(tools=tools)

    logger.info(
        "[API] Assembled prompt: task=%s, layers=%s, tools=%s",
        assembled.task,
        assembled.layers_used,
        assembled.tool_count,
    )

    return Message(role="system", content=assembled.system_prompt)


async def _run_tool_only_call(
    *,
    tool_call: dict[str, Any],
    allowed: set[str],
) -> dict[str, Any]:
    tool_name = _canonicalize_tool_name(tool_call.get("name", ""), allowed)
    tool_args = tool_call.get("arguments") or {}
    try:
        tool_result = await _execute_tool_call(
            tool_name,
            tool_args,
            allowed,
        )
    except MarketServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Error executing tool call")
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    return {
        "text": json.dumps(tool_result, indent=2),
        "_meta": {
            "tool_calls": [
                _tool_activity_entry(
                    tool_name=tool_name,
                    arguments=tool_args,
                    success=True,
                    result=tool_result,
                )
            ]
        },
    }


class ChatApplicationService:
    """Orchestrates non-streaming and streaming chat flows."""

    def __init__(self, tracer: LangfuseTracer | None = None) -> None:
        self._langfuse = tracer or LangfuseTracer()

    async def list_ollama_models(self) -> dict[str, Any]:
        try:
            async with ProviderFactory.create("ollama") as provider:
                response = await provider.list_models()
                raw_models = response.get("models", [])
                model_entries = [
                    m for m in raw_models
                    if isinstance(m, dict) and _normalize_ollama_model_name(m.get("name"))
                ]
                model_names = [_normalize_ollama_model_name(m.get("name")) for m in model_entries]
                thinking_infos = await asyncio.gather(
                    *(_ollama_model_thinking_info(provider, name) for name in model_names),
                    return_exceptions=True,
                )

                enriched = []
                for name, raw, thinking in zip(model_names, model_entries, thinking_infos):
                    if isinstance(thinking, Exception):
                        thinking = dict(_EMPTY_THINKING_INFO)
                    enriched.append(
                        {
                            "name": name,
                            "size": raw.get("size"),
                            "modified_at": raw.get("modified_at"),
                            "digest": raw.get("digest"),
                            "thinking": thinking,
                        }
                    )

                return {"models": enriched}
        except Exception as exc:
            logger.exception("Error listing models")
            raise HTTPException(status_code=500, detail="Internal server error") from exc

    async def chat(self, request: ChatRequest) -> Any:
        logger.info(
            "[API] Chat request: provider=%s, model=%s, stream=%s, messages=%s",
            request.provider,
            request.model,
            request.stream,
            len(request.messages),
        )

        messages = [msg.to_message() for msg in request.messages]
        options = dict(request.options or {})
        mcp_config = options.pop("mcp", {})
        reasoning_config = _parse_reasoning_config(options.pop("reasoning", {}))
        langfuse_options = _parse_langfuse_options(options.pop("langfuse", {}))

        max_tokens = int(options.pop("max_tokens", 1024)) if request.provider == "anthropic" else None

        mcp_enabled = bool(mcp_config.get("enabled"))
        allowed = _allowed_tools(mcp_config) if mcp_enabled else set()
        if mcp_enabled and not allowed:
            logger.info("[API] MCP enabled but no tools are allowed; skipping tool routing.")
            mcp_enabled = False

        if mcp_enabled and not request.stream:
            tool_call = mcp_config.get("tool_call") or {}
            if mcp_config.get("tool_only") and tool_call:
                return await _run_tool_only_call(tool_call=tool_call, allowed=allowed)

        try:
            provider = ProviderFactory.create(request.provider, api_key=request.api_key)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        kwargs = _build_provider_kwargs(
            provider_name=request.provider,
            model=request.model,
            options=options,
            max_tokens=max_tokens,
            reasoning_config=reasoning_config,
        )

        if not request.stream:
            try:
                async with provider:
                    system_prompt = _build_system_prompt(allowed)
                    loop_result: ToolLoopResult | None = None

                    if mcp_enabled:
                        loop_result = await _run_tool_loop(
                            provider=provider,
                            provider_name=request.provider,
                            model=request.model,
                            kwargs=kwargs,
                            system_prompt=system_prompt,
                            messages=messages,
                            allowed=allowed,
                            direct_tool_call=mcp_config.get("tool_call"),
                        )

                    tool_activity = loop_result.tool_activity if loop_result else []
                    tool_context = loop_result.tool_context if loop_result else []
                    response_text = loop_result.response_text if loop_result else None
                    rounds = loop_result.rounds if loop_result else []

                    preamble = _tool_preamble(tool_activity)

                    # If the tool loop produced a text response, use it directly
                    if response_text is not None:
                        result: dict[str, Any] = {"text": preamble + response_text}
                        meta = _build_response_meta(tool_activity=tool_activity, rounds=rounds)
                        if meta:
                            result["_meta"] = meta
                        return result

                    # Otherwise make a final response call
                    final_messages = [system_prompt, *messages, *tool_context]

                    trace_metadata = _build_langfuse_request_metadata(
                        request=request,
                        mcp_enabled=mcp_enabled,
                        reasoning_config=reasoning_config,
                        langfuse_options=langfuse_options,
                    )
                    generation_name = str(
                        langfuse_options.get("generation_name") or "chat.completion"
                    )
                    with self._langfuse.start_generation(
                        name=generation_name,
                        model=request.model,
                        prompt=_messages_to_trace_payload(final_messages),
                        model_parameters=kwargs,
                        metadata=trace_metadata,
                    ) as generation:
                        try:
                            response = await provider.chat(final_messages, model=request.model, **kwargs)
                            result = {"text": preamble + _extract_text(request.provider, response)}
                            meta = _build_response_meta(tool_activity=tool_activity, rounds=rounds)
                            if meta:
                                result["_meta"] = meta

                            self._langfuse.update_generation(
                                generation,
                                output=result["text"],
                                usage_details=_extract_usage_details(request.provider, response),
                                metadata={"tool_call_count": len(tool_activity)},
                            )
                            return result
                        except Exception as exc:
                            self._langfuse.update_generation(
                                generation,
                                status_message=str(exc),
                                metadata={"error_type": type(exc).__name__},
                            )
                            raise
                        finally:
                            self._langfuse.flush()
            except Exception as exc:
                logger.error("[API] Error in non-streaming chat: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Internal server error") from exc

        # Streaming path
        async def stream() -> AsyncIterator[str]:
            text_parts: list[str] = []
            tool_activity: list[dict[str, Any]] = []
            rounds: list[dict[str, Any]] = []
            try:
                logger.info("[API] Starting stream for provider=%s", request.provider)
                async with provider:
                    system_prompt = _build_system_prompt(allowed)
                    loop_result: ToolLoopResult | None = None

                    if mcp_enabled:
                        loop_result = await _run_tool_loop(
                            provider=provider,
                            provider_name=request.provider,
                            model=request.model,
                            kwargs=kwargs,
                            system_prompt=system_prompt,
                            messages=messages,
                            allowed=allowed,
                            direct_tool_call=mcp_config.get("tool_call"),
                        )
                        tool_activity = loop_result.tool_activity
                        tool_context = loop_result.tool_context
                        response_text = loop_result.response_text
                        rounds = loop_result.rounds
                    else:
                        tool_context = []
                        response_text = None

                    preamble = _tool_preamble(tool_activity)

                    if response_text is not None:
                        # Tool loop produced text — emit with preamble
                        full_text = preamble + response_text
                        text_parts.append(full_text)
                        yield _sse({"type": "delta", "text": full_text})
                    else:
                        # Stream the final response (emit preamble first)
                        if preamble:
                            text_parts.append(preamble)
                            yield _sse({"type": "delta", "text": preamble})
                        final_messages = [system_prompt, *messages, *tool_context]

                        trace_metadata = _build_langfuse_request_metadata(
                            request=request,
                            mcp_enabled=mcp_enabled,
                            reasoning_config=reasoning_config,
                            langfuse_options=langfuse_options,
                        )
                        generation_name = str(
                            langfuse_options.get("generation_name") or "chat.completion.stream"
                        )
                        with self._langfuse.start_generation(
                            name=generation_name,
                            model=request.model,
                            prompt=_messages_to_trace_payload(final_messages),
                            model_parameters=kwargs,
                            metadata=trace_metadata,
                        ) as generation:
                            try:
                                async for chunk in provider.stream_chat(
                                    final_messages,
                                    model=request.model,
                                    **kwargs,
                                ):
                                    delta = _extract_stream_delta(request.provider, chunk)
                                    if delta:
                                        text_parts.append(delta)
                                        yield _sse({"type": "delta", "text": delta})
                                self._langfuse.update_generation(
                                    generation,
                                    output="".join(text_parts),
                                    metadata={"tool_call_count": len(tool_activity)},
                                )
                            except Exception as exc:
                                self._langfuse.update_generation(
                                    generation,
                                    status_message=str(exc),
                                    metadata={"error_type": type(exc).__name__},
                                )
                                raise
                            finally:
                                self._langfuse.flush()

                complete_text = "".join(text_parts)
                logger.info("[API] Stream completed, total text length: %s", len(complete_text))
                done_event: dict[str, Any] = {
                    "type": "done",
                    "text": complete_text,
                    "provider": request.provider,
                    "model": request.model,
                }
                meta = _build_response_meta(tool_activity=tool_activity, rounds=rounds)
                if meta:
                    done_event["_meta"] = meta
                yield _sse(done_event)
            except Exception as exc:
                logger.error("[API] Error in stream: %s", exc, exc_info=True)
                yield _sse({"type": "error", "message": str(exc)})

        logger.info("[API] Returning StreamingResponse")
        return StreamingResponse(stream(), media_type="text/event-stream")


chat_service = ChatApplicationService()
