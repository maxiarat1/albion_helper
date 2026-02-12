"""Tests for shared MCP item resolution helpers."""

from unittest.mock import patch

from app.mcp.tools._resolve import (
    attach_smart_resolution,
    capped_limit,
    normalize_item_input,
    resolve_item_smart,
    resolve_with_smart_item,
)


def test_normalize_item_input_extracts_canonical_id_from_decorated_text():
    raw = "\nT4_BAG\n(T4)\n(Adept's Bag)\n"
    assert normalize_item_input(raw) == "T4_BAG"


def test_resolve_item_smart_uses_normalized_query():
    mock_match = type(
        "Match",
        (),
        {
            "unique_name": "T4_BAG",
            "display_name": "Adept's Bag",
        },
    )()
    mock_resolution = type(
        "Resolution",
        (),
        {
            "resolved": True,
            "matches": [mock_match],
        },
    )()

    with patch("app.mcp.tools._resolve.smart_resolver") as mock_resolver:
        mock_resolver.resolve.return_value = mock_resolution

        item_id, note = resolve_item_smart("\nT4_BAG\n(T4)\n")

    assert item_id == "T4_BAG"
    assert note is not None
    assert note["resolved_from"] == "\nT4_BAG\n(T4)\n"
    mock_resolver.resolve.assert_called_once_with("T4_BAG", limit=5)


def test_resolve_with_smart_item_retries_lookup():
    with patch("app.mcp.tools._resolve.resolve_item_smart", return_value=("T4_BAG", {"ok": True})):
        item, note = resolve_with_smart_item(
            "T4 Bag",
            lambda item_id: {"id": item_id} if item_id == "T4_BAG" else None,
        )

    assert item == {"id": "T4_BAG"}
    assert note == {"ok": True}


def test_attach_smart_resolution_noop_when_note_missing():
    payload = {"x": 1}
    updated = attach_smart_resolution(payload, None)
    assert updated == {"x": 1}
    assert "smart_resolution" not in updated


def test_attach_smart_resolution_adds_note():
    payload = {"x": 1}
    updated = attach_smart_resolution(payload, {"resolved_to": "T4_BAG"})
    assert updated["smart_resolution"]["resolved_to"] == "T4_BAG"


def test_capped_limit_uses_default_and_max():
    assert capped_limit(None, default=20, maximum=50) == 20
    assert capped_limit(100, default=20, maximum=50) == 50
