"""Reusable MCP tool schema and annotation templates.

These helpers keep tool declarations consistent across modules.
"""

from __future__ import annotations

from app.mcp.registry import Param, ToolAnnotations

_QUALITY_ENUM = [1, 2, 3, 4, 5]

# Common annotation presets
READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)

MUTATING_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def item_param(
    *,
    required: bool = True,
    description: str = "Item name or ID (display name or unique item ID).",
) -> Param:
    return Param(
        "item",
        "string",
        description,
        required=required,
        min_length=1,
    )


def query_param(
    *,
    required: bool = False,
    description: str = "Search query.",
) -> Param:
    return Param(
        "query",
        "string",
        description,
        required=required,
        min_length=1 if required else None,
    )


def limit_param(
    *,
    description: str,
    required: bool = False,
    minimum: int = 1,
    maximum: int | None = None,
) -> Param:
    return Param(
        "limit",
        "integer",
        description,
        required=required,
        minimum=minimum,
        maximum=maximum,
    )


def quality_param(
    *,
    required: bool = False,
    description: str = (
        "Quality filter: 1=Normal, 2=Good, 3=Outstanding, "
        "4=Excellent, 5=Masterpiece."
    ),
) -> Param:
    return Param(
        "quality",
        "integer",
        description,
        required=required,
        enum=_QUALITY_ENUM,
    )


def cities_param(
    *,
    required: bool = False,
    description: str = "Cities to query.",
) -> Param:
    return Param(
        "cities",
        "array",
        description,
        required=required,
        items_type="string",
    )


def start_date_param(*, required: bool = False) -> Param:
    return Param(
        "start_date",
        "string",
        "Start date (YYYY-MM-DD).",
        required=required,
        format="date",
    )


def end_date_param(*, required: bool = False) -> Param:
    return Param(
        "end_date",
        "string",
        "End date (YYYY-MM-DD).",
        required=required,
        format="date",
    )
