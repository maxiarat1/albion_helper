"""Shared item resolution utility for MCP tools."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, TypeVar

from app.data.item_resolver import smart_resolver

_CANONICAL_ITEM_ID_RE = re.compile(r"\b(T[1-8](?:_[A-Z0-9]+)+(?:@\d+)?)\b", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_ResolutionNote = dict[str, Any] | None
T = TypeVar("T")


def normalize_item_input(item: str) -> str:
    """Normalize item input coming from model/tool context.

    Handles common artifacts from rendered text such as:
    - line breaks around IDs
    - parenthetical suffixes like ``(T4)`` or ``(Adept's Bag)``
    - surrounding markdown/code quoting
    """
    text = str(item or "").strip()
    if not text:
        return ""

    # Collapse whitespace/newlines first.
    text = _WHITESPACE_RE.sub(" ", text).strip()
    text = text.strip("`'\"")

    # If a canonical item ID appears anywhere, prefer that exact token.
    match = _CANONICAL_ITEM_ID_RE.search(text)
    if match:
        return match.group(1).upper()

    return text


def resolve_item_smart(item: str) -> tuple[str, dict[str, Any] | None]:
    """Resolve an item name/query to a canonical item ID using fuzzy matching.

    Returns ``(resolved_item_id, resolution_note)`` where *resolution_note*
    is ``None`` when the input already matched exactly, or a dict describing
    what was resolved (with optional alternatives) when fuzzy matching was
    applied.
    """
    original_item = str(item or "")
    normalized_item = normalize_item_input(original_item)
    resolution = smart_resolver.resolve(normalized_item, limit=5)

    if resolution.matches:
        best_match = resolution.matches[0]
        note = None

        best_matches_input = best_match.unique_name.casefold() == normalized_item.casefold()
        input_was_normalized = original_item.strip() != normalized_item
        if not best_matches_input or input_was_normalized:
            note = {
                "resolved_from": original_item,
                "resolved_to": best_match.display_name,
                "item_id": best_match.unique_name,
            }
            if not resolution.resolved and len(resolution.matches) > 1:
                note["alternatives"] = [
                    {"name": m.display_name, "id": m.unique_name}
                    for m in resolution.matches[1:3]
                ]

        return best_match.unique_name, note

    return normalized_item, None


def resolve_with_smart_item(
    query: str,
    lookup: Callable[[str], T | None],
) -> tuple[T | None, _ResolutionNote]:
    """Look up a resource by item query, then retry with smart item resolution."""
    resolved = lookup(query)
    if resolved:
        return resolved, None

    resolved_id, resolution_note = resolve_item_smart(query)
    if resolved_id != query:
        resolved = lookup(resolved_id)
    return resolved, resolution_note


def attach_smart_resolution(
    payload: dict[str, Any],
    resolution_note: _ResolutionNote,
) -> dict[str, Any]:
    """Attach smart-resolution metadata only when available."""
    if resolution_note:
        payload["smart_resolution"] = resolution_note
    return payload


def capped_limit(value: Any, *, default: int, maximum: int) -> int:
    """Apply tool-level max cap while preserving existing type semantics."""
    candidate = value if value is not None else default
    return min(candidate, maximum)
