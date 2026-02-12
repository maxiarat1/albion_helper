"""Output schema definitions for structured AI responses.

Provides a standard envelope for all agent responses, enabling:
- Consistent parsing across different LLM providers
- Type-safe response handling in the frontend
- Clear distinction between text, data, actions, and errors

Usage:
    response = AgentResponse.parse(raw_text)
    if response.type == ResponseType.ACTION:
        handle_tool_call(response)
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)
_EMBEDDED_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class ResponseType(StrEnum):
    """Types of agent responses."""

    TEXT = "text"      # Free-form text response
    DATA = "data"      # Structured data (JSON)
    ACTION = "action"  # Tool call request
    ERROR = "error"    # Error response


class AgentResponse(BaseModel):
    """Base response envelope for all agent outputs.

    All LLM responses are normalized into this format, providing
    a consistent interface regardless of the underlying model.
    """

    type: ResponseType = Field(description="Response type discriminator")
    content: str | dict[str, Any] = Field(description="Response payload")
    metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata (source, timing, etc.)"
    )

    @classmethod
    def text(cls, content: str, **metadata: Any) -> "TextResponse":
        """Create a text response."""
        return TextResponse(content=content, metadata=metadata or None)

    @classmethod
    def data(
        cls, content: dict[str, Any], schema_ref: str | None = None, **metadata: Any
    ) -> "DataResponse":
        """Create a structured data response."""
        return DataResponse(
            content=content, schema_ref=schema_ref, metadata=metadata or None
        )

    @classmethod
    def action(
        cls, tool: str, arguments: dict[str, Any], **metadata: Any
    ) -> "ActionRequest":
        """Create a tool action request."""
        return ActionRequest(
            tool=tool, arguments=arguments, metadata=metadata or None
        )

    @classmethod
    def error(cls, message: str, code: str | None = None, **metadata: Any) -> "ErrorResponse":
        """Create an error response."""
        return ErrorResponse(
            content=message, error_code=code, metadata=metadata or None
        )

    @classmethod
    def parse(cls, raw: str, expected: ResponseType | None = None) -> "AgentResponse":
        """Parse raw LLM output into structured response.

        Attempts to detect the response type from content structure.
        If expected is provided, validates the result matches.

        Args:
            raw: Raw text from LLM
            expected: Optional expected response type for validation

        Returns:
            Parsed AgentResponse subclass
        """
        raw = raw.strip()
        parsed_json = _try_parse_json(raw)
        if parsed_json is None:
            response: AgentResponse = TextResponse(content=raw)
        else:
            response = _build_response_from_json(parsed_json=parsed_json, raw=raw)

        # Validate against expected type if provided
        if expected and response.type != expected:
            logger.warning(
                "Response type mismatch: expected %s, got %s",
                expected,
                response.type,
            )

        return response


class TextResponse(AgentResponse):
    """Free-form text response from the agent."""

    type: Literal[ResponseType.TEXT] = ResponseType.TEXT
    content: str


class DataResponse(AgentResponse):
    """Structured data response (JSON)."""

    type: Literal[ResponseType.DATA] = ResponseType.DATA
    content: dict[str, Any]
    schema_ref: str | None = Field(
        default=None, description="Reference to JSON schema for validation"
    )


class ActionRequest(AgentResponse):
    """Request to execute a tool/action."""

    type: Literal[ResponseType.ACTION] = ResponseType.ACTION
    content: dict[str, Any] = Field(default_factory=dict)
    tool: str = Field(description="Tool name to invoke")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Tool arguments"
    )

    @model_validator(mode="after")
    def sync_content(self) -> "ActionRequest":
        """Keep content in sync with tool/arguments for serialization."""
        self.content = {"tool": self.tool, "arguments": self.arguments}
        return self


class ErrorResponse(AgentResponse):
    """Error response from the agent or system."""

    type: Literal[ResponseType.ERROR] = ResponseType.ERROR
    content: str  # Error message
    error_code: str | None = Field(
        default=None, description="Machine-readable error code"
    )


def _build_response_from_json(parsed_json: dict[str, Any], raw: str) -> AgentResponse:
    """Map parsed JSON payload into the correct response envelope."""
    if "tool" in parsed_json and parsed_json.get("tool"):
        return ActionRequest(
            tool=parsed_json["tool"],
            arguments=parsed_json.get("arguments", {}),
        )
    if "tool" in parsed_json and parsed_json.get("tool") is None:
        # Explicit "no tool needed" signal
        return TextResponse(content=raw)
    return DataResponse(content=parsed_json)


def _parse_json_dict(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _strip_markdown_code_fence(text: str) -> str:
    """Remove leading/trailing markdown code fences when present."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.split("\n", 1)
    if len(lines) > 1:
        cleaned = lines[1]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def _extract_embedded_json_dict(text: str) -> dict[str, Any] | None:
    match = _EMBEDDED_JSON_OBJECT_RE.search(text)
    if not match:
        return None
    return _parse_json_dict(match.group())


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Attempt to parse text as JSON, handling markdown code blocks."""
    cleaned = _strip_markdown_code_fence(text)

    parsed_direct = _parse_json_dict(cleaned)
    if parsed_direct is not None:
        return parsed_direct

    return _extract_embedded_json_dict(cleaned)
