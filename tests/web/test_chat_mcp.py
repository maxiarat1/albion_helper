"""Tests for MCP integration in chat."""

import json
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.web.main import app


client = TestClient(app)


def test_chat_mcp_tool_only_resolve_item():
    with patch("app.mcp.tools.gamedata.smart_resolver") as mock_resolver:
        mock_result = type("Result", (), {
            "resolved": True,
            "matches": [type("Match", (), {
                "unique_name": "T4_BAG",
                "display_name": "T4 Bag",
            })()],
            "to_dict": lambda self: {
                "resolved": True,
                "query": "T4 Bag",
                "matches": [{"unique_name": "T4_BAG", "display_name": "T4 Bag"}],
            },
        })()
        mock_resolver.resolve.return_value = mock_result

        response = client.post(
            "/chat",
            json={
                "provider": "anthropic",
                "model": "claude-3-sonnet",
                "messages": [{"role": "user", "content": "resolve T4 Bag"}],
                "stream": False,
                "options": {
                    "mcp": {
                        "enabled": True,
                        "tool_only": True,
                        "tool_call": {"name": "resolve_item", "arguments": {"query": "T4 Bag"}},
                    }
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    payload = json.loads(body["text"])
    assert payload["resolved"] is True
    assert body["_meta"]["tool_calls"][0]["tool"] == "resolve_item"
    assert body["_meta"]["tool_calls"][0]["type"] == "tool_call"


def test_chat_mcp_tool_only_normalizes_tool_name():
    with patch("app.mcp.tools.gamedata.smart_resolver") as mock_resolver:
        mock_result = type("Result", (), {
            "resolved": True,
            "matches": [type("Match", (), {
                "unique_name": "T4_BAG",
                "display_name": "T4 Bag",
            })()],
            "to_dict": lambda self: {
                "resolved": True,
                "query": "T4 Bag",
                "matches": [{"unique_name": "T4_BAG", "display_name": "T4 Bag"}],
            },
        })()
        mock_resolver.resolve.return_value = mock_result

        response = client.post(
            "/chat",
            json={
                "provider": "anthropic",
                "model": "claude-3-sonnet",
                "messages": [{"role": "user", "content": "resolve T4 Bag"}],
                "stream": False,
                "options": {
                    "mcp": {
                        "enabled": True,
                        "tool_only": True,
                        "tool_call": {"name": " Resolve-Item ", "arguments": {"query": "T4 Bag"}},
                    }
                },
            },
        )

    assert response.status_code == 200
    body = response.json()
    payload = json.loads(body["text"])
    assert payload["resolved"] is True
    assert body["_meta"]["tool_calls"][0]["tool"] == "resolve_item"


def test_chat_mcp_blocks_duplicate_tool_calls():
    """Tool loop: first call succeeds, second identical call is blocked, third returns text."""
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.side_effect = [
        # Iteration 0: tool call → execute
        {"content": [{"text": '{"tool":"search_items","arguments":{"query":"depth","limit":5}}'}]},
        # Iteration 1: duplicate → blocked, continue
        {"content": [{"text": '{"tool":"search_items","arguments":{"query":"depth","limit":5}}'}]},
        # Iteration 2: text response → done (no separate final call needed)
        {"content": [{"text": "Depths is an activity mode."}]},
    ]

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        with patch("app.mcp.tools.gamedata.game_db.search_items", return_value=[]):
            response = client.post(
                "/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-3-sonnet",
                    "messages": [{"role": "user", "content": "I want to play depths"}],
                    "stream": False,
                    "options": {
                        "mcp": {
                            "enabled": True,
                        }
                    },
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["text"].endswith("Depths is an activity mode.")
    assert "[Used tools:" in body["text"]
    assert len(body["_meta"]["tool_calls"]) == 2
    assert body["_meta"]["tool_calls"][0]["success"] is True
    assert body["_meta"]["tool_calls"][1]["success"] is False
    assert "Duplicate tool call blocked" in body["_meta"]["tool_calls"][1]["error"]


def test_chat_mcp_stops_repeated_duplicate_tool_call_spam():
    """Repeated duplicate breaks the loop; final response call produces text."""
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.side_effect = [
        # Iteration 0: tool call → execute
        {"content": [{"text": '{"tool":"search_items","arguments":{"query":"depth","limit":5}}'}]},
        # Iteration 1: first dup → blocked, continue
        {"content": [{"text": '{"tool":"search_items","arguments":{"query":"depth","limit":5}}'}]},
        # Iteration 2: repeated dup → break (response_text=None)
        {"content": [{"text": '{"tool":"search_items","arguments":{"query":"depth","limit":5}}'}]},
        # Final response call (since loop broke without text)
        {"content": [{"text": "Depths is an activity mode."}]},
    ]

    with patch("app.web.main.ProviderFactory.create", return_value=mock_provider):
        with patch("app.mcp.tools.gamedata.game_db.search_items", return_value=[]):
            response = client.post(
                "/chat",
                json={
                    "provider": "anthropic",
                    "model": "claude-3-sonnet",
                    "messages": [{"role": "user", "content": "I want to play depths"}],
                    "stream": False,
                    "options": {
                        "mcp": {
                            "enabled": True,
                        }
                    },
                },
            )

    assert response.status_code == 200
    body = response.json()
    assert body["text"].endswith("Depths is an activity mode.")
    assert "[Used tools:" in body["text"]
    assert len(body["_meta"]["tool_calls"]) == 2
    duplicate_errors = [
        t for t in body["_meta"]["tool_calls"]
        if t["success"] is False and "Duplicate tool call blocked" in t.get("error", "")
    ]
    assert len(duplicate_errors) == 1


def test_chat_mcp_forces_market_data_fallback_for_price_intent():
    """If model ignores tool JSON for a price query, backend should force market_data once."""
    mock_provider = AsyncMock()
    mock_provider.__aenter__.return_value = mock_provider
    mock_provider.__aexit__.return_value = None
    mock_provider.chat.side_effect = [
        # Iteration 0: model ignores tool contract and returns prose
        {"content": [{"text": "The price varies a lot by market conditions."}]},
        # Iteration 1: after forced tool result was injected, model returns final text
        {"content": [{"text": "Best sell for T4_BAG is 4800 silver in Martlock."}]},
    ]

    with (
        patch("app.web.main.ProviderFactory.create", return_value=mock_provider),
        patch("app.mcp.tools.market.resolve_item_smart", return_value=("T4_BAG", None)),
        patch("app.mcp.tools.market.market_app") as mock_market,
    ):
        mock_market.get_market_prices = AsyncMock(
            return_value={
                "item": "T4_BAG",
                "data": [
                    {
                        "location": "Martlock",
                        "sell_price_min": 4800,
                        "sell_price_min_date": "2026-02-10T00:00:00",
                        "buy_price_max": 4300,
                        "buy_price_max_date": "2026-02-10T00:00:00",
                    }
                ],
            }
        )

        response = client.post(
            "/chat",
            json={
                "provider": "anthropic",
                "model": "claude-3-sonnet",
                "messages": [{"role": "user", "content": "what is the cost of t4 bag"}],
                "stream": False,
                "options": {"mcp": {"enabled": True}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"].endswith("Best sell for T4_BAG is 4800 silver in Martlock.")
    assert "[Used tools:" in body["text"]
    assert len(body["_meta"]["tool_calls"]) == 1
    assert body["_meta"]["tool_calls"][0]["tool"] == "market_data"
    assert body["_meta"]["tool_calls"][0]["success"] is True
    assert body["_meta"]["tool_calls"][0]["arguments"]["item"] == "t4 bag"
    assert body["_meta"]["tool_calls"][0]["arguments"]["mode"] == "snapshot"
