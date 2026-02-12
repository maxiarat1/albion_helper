"""Registry for MCP tools following Model Context Protocol specification."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]
ToolVisibility = Literal["public", "admin"]


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    """Declarative parameter definition that compiles to JSON Schema."""

    name: str
    type: str  # "string", "integer", "boolean", "array", "number", "object"
    description: str
    required: bool = False
    enum: list[str] | list[int] | None = None
    items_type: str | None = None  # only for type="array"
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    format: str | None = None

    def to_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum is not None:
            schema["enum"] = self.enum
        if self.type == "array" and self.items_type:
            schema["items"] = {"type": self.items_type}
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.min_length is not None:
            schema["minLength"] = self.min_length
        if self.max_length is not None:
            schema["maxLength"] = self.max_length
        if self.pattern is not None:
            schema["pattern"] = self.pattern
        if self.format is not None:
            schema["format"] = self.format
        return schema


@dataclass(frozen=True)
class ToolAnnotations:
    """MCP tool annotations that hint execution semantics to clients/models."""

    read_only_hint: bool | None = None
    destructive_hint: bool | None = None
    idempotent_hint: bool | None = None
    open_world_hint: bool | None = None

    def to_mcp_format(self) -> dict[str, bool]:
        payload: dict[str, bool] = {}
        if self.read_only_hint is not None:
            payload["readOnlyHint"] = self.read_only_hint
        if self.destructive_hint is not None:
            payload["destructiveHint"] = self.destructive_hint
        if self.idempotent_hint is not None:
            payload["idempotentHint"] = self.idempotent_hint
        if self.open_world_hint is not None:
            payload["openWorldHint"] = self.open_world_hint
        return payload


def build_input_schema(
    params: list[Param],
    *,
    additional_properties: bool = False,
) -> dict[str, Any]:
    """Build a JSON Schema object from a list of Params."""
    properties = {p.name: p.to_schema() for p in params}
    required = [p.name for p in params if p.required]

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """MCP-compliant tool specification."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    title: str | None = None
    annotations: ToolAnnotations | None = None
    output_schema: dict[str, Any] | None = None
    visibility: ToolVisibility = "public"

    def to_mcp_format(self) -> dict[str, Any]:
        """Convert to MCP-compliant tool definition."""
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.title:
            payload["title"] = self.title
        if self.output_schema is not None:
            payload["outputSchema"] = self.output_schema
        if self.annotations is not None:
            annotations = self.annotations.to_mcp_format()
            if annotations:
                payload["annotations"] = annotations
        return payload


@dataclass
class ToolResult:
    """MCP-compliant tool result."""

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    structured_content: Any | None = None

    @classmethod
    def text(cls, text: str) -> ToolResult:
        """Create a text content result."""
        return cls(content=[{"type": "text", "text": text}])

    @classmethod
    def json(cls, data: Any) -> ToolResult:
        """Create a result with both structured and text content."""
        return cls(
            content=[{"type": "text", "text": json.dumps(data, indent=2)}],
            structured_content=data,
        )

    @classmethod
    def error(cls, message: str) -> ToolResult:
        """Create an error result."""
        return cls(content=[{"type": "text", "text": message}], is_error=True)

    def to_mcp_format(self) -> dict[str, Any]:
        """Convert to MCP-compliant response format."""
        payload: dict[str, Any] = {
            "content": self.content,
            "isError": self.is_error,
        }
        if self.structured_content is not None:
            payload["structuredContent"] = self.structured_content
        return payload


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Stores tool definitions and validates inputs per MCP specification."""

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def list_tools(self, *, include_admin: bool = False) -> list[dict[str, Any]]:
        """Return tools in MCP-compliant format."""
        specs = self._tools.values()
        if not include_admin:
            specs = [spec for spec in specs if spec.visibility == "public"]
        return [spec.to_mcp_format() for spec in specs]

    def get(self, name: str, *, include_admin: bool = False) -> ToolSpec | None:
        spec = self._tools.get(name)
        if spec is None:
            return None
        if spec.visibility == "public" or include_admin:
            return spec
        return None

    def validate(self, schema: dict[str, Any], args: dict[str, Any]) -> None:
        """Validate arguments against JSON Schema subset used by this project.

        Raises ValueError with descriptive message on validation failure.
        """
        if not isinstance(args, dict):
            raise ValueError("Arguments must be an object")

        required = schema.get("required", [])
        for field_name in required:
            if field_name not in args:
                raise ValueError(f"Missing required field: '{field_name}'")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties", True) is False:
            unknown_fields = sorted(set(args) - set(properties))
            if unknown_fields:
                raise ValueError(
                    "Unknown field(s): " + ", ".join(f"'{name}'" for name in unknown_fields)
                )

        for key, value in args.items():
            prop = properties.get(key)
            if prop is None:
                continue
            self._validate_value(path=key, value=value, schema=prop)

    def _validate_value(self, *, path: str, value: Any, schema: dict[str, Any]) -> None:
        expected_type = schema.get("type")
        if expected_type is not None:
            self._validate_type(path=path, value=value, expected_type=expected_type)

        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            raise ValueError(f"Field '{path}' must be one of {enum_values}")

        if expected_type in {"integer", "number"}:
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                raise ValueError(f"Field '{path}' must be >= {minimum}")
            if maximum is not None and value > maximum:
                raise ValueError(f"Field '{path}' must be <= {maximum}")

        if expected_type == "string":
            min_len = schema.get("minLength")
            max_len = schema.get("maxLength")
            if min_len is not None and len(value) < min_len:
                raise ValueError(f"Field '{path}' must be at least {min_len} chars")
            if max_len is not None and len(value) > max_len:
                raise ValueError(f"Field '{path}' must be at most {max_len} chars")

            pattern = schema.get("pattern")
            if pattern and not re.search(pattern, value):
                raise ValueError(f"Field '{path}' has invalid format")

            field_format = schema.get("format")
            if field_format == "date" and value and not self._DATE_RE.match(value):
                raise ValueError(f"Field '{path}' must be a date in YYYY-MM-DD format")

        if expected_type == "array":
            items_schema = schema.get("items")
            if isinstance(items_schema, dict):
                for idx, item in enumerate(value):
                    self._validate_value(path=f"{path}[{idx}]", value=item, schema=items_schema)

        if expected_type == "object":
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            for required_key in required:
                if required_key not in value:
                    raise ValueError(f"Field '{path}.{required_key}' is required")

            if schema.get("additionalProperties", True) is False:
                unknown_fields = sorted(set(value) - set(properties))
                if unknown_fields:
                    raise ValueError(
                        f"Field '{path}' has unknown subfield(s): "
                        + ", ".join(f"'{name}'" for name in unknown_fields)
                    )

            for key, val in value.items():
                nested_schema = properties.get(key)
                if nested_schema is None:
                    continue
                self._validate_value(path=f"{path}.{key}", value=val, schema=nested_schema)

    @staticmethod
    def _validate_type(*, path: str, value: Any, expected_type: str) -> None:
        if expected_type == "string" and not isinstance(value, str):
            raise ValueError(f"Field '{path}' must be a string")
        if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"Field '{path}' must be an integer")
        if expected_type == "number" and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ValueError(f"Field '{path}' must be a number")
        if expected_type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"Field '{path}' must be a boolean")
        if expected_type == "array" and not isinstance(value, list):
            raise ValueError(f"Field '{path}' must be an array")
        if expected_type == "object" and not isinstance(value, dict):
            raise ValueError(f"Field '{path}' must be an object")
        if expected_type == "null" and value is not None:
            raise ValueError(f"Field '{path}' must be null")


registry = ToolRegistry()


# ---------------------------------------------------------------------------
# @tool decorator
# ---------------------------------------------------------------------------


def tool(
    name: str,
    description: str,
    params: list[Param] | None = None,
    *,
    title: str | None = None,
    annotations: ToolAnnotations | None = None,
    output_schema: dict[str, Any] | None = None,
    visibility: ToolVisibility = "public",
    additional_properties: bool = False,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator that registers an async function as an MCP tool."""

    def decorator(fn: ToolHandler) -> ToolHandler:
        spec = ToolSpec(
            name=name,
            title=title,
            description=description,
            input_schema=build_input_schema(
                params or [],
                additional_properties=additional_properties,
            ),
            output_schema=output_schema,
            annotations=annotations,
            visibility=visibility,
            handler=fn,
        )
        registry.register(spec)
        return fn

    return decorator
