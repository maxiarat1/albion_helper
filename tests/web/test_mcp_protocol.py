"""Tests for MCP-compliant protocol endpoints."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.web.main import app


client = TestClient(app)


def test_mcp_tools_list_returns_compliant_format():
    """Test that POST /mcp/tools/list returns MCP-compliant format."""
    response = client.post("/mcp/tools/list")
    assert response.status_code == 200

    data = response.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)

    # Verify at least one tool exists
    assert len(data["tools"]) >= 1

    # Verify tool structure matches MCP spec
    for tool in data["tools"]:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        assert isinstance(tool["inputSchema"], dict)


def test_mcp_tools_call_success_returns_content_blocks():
    """Test that successful tool call returns MCP content blocks."""
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
            "/mcp/tools/call",
            json={"name": "resolve_item", "arguments": {"query": "T4 Bag"}},
        )

    assert response.status_code == 200
    data = response.json()

    # MCP-compliant response structure
    assert "content" in data
    assert "isError" in data
    assert data["isError"] is False
    assert isinstance(data["content"], list)
    assert len(data["content"]) >= 1
    assert data["content"][0]["type"] == "text"
    assert "structuredContent" in data


def test_mcp_tools_call_unknown_tool_returns_error():
    """Test that calling unknown tool returns isError=true."""
    response = client.post(
        "/mcp/tools/call",
        json={"name": "nonexistent_tool", "arguments": {}},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["isError"] is True
    assert "content" in data
    assert "not found" in data["content"][0]["text"].lower()


def test_mcp_tools_call_validation_error_returns_error():
    """Test that validation errors return isError=true with message."""
    response = client.post(
        "/mcp/tools/call",
        json={"name": "market_data", "arguments": {}},  # Missing required 'item' field
    )

    assert response.status_code == 200
    data = response.json()

    assert data["isError"] is True
    assert "Invalid arguments" in data["content"][0]["text"]


def test_mcp_tools_call_rejects_unknown_fields():
    """Unknown arguments should be rejected for strict schemas."""
    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "resolve_item",
            "arguments": {"query": "T4 Bag", "unexpected": "value"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is True
    assert "Unknown field" in data["content"][0]["text"]


def test_mcp_resolve_item_normalizes_decorated_id_query():
    with patch("app.mcp.tools.gamedata.smart_resolver") as mock_resolver:
        mock_result = type("Result", (), {
            "resolved": True,
            "matches": [type("Match", (), {
                "unique_name": "T4_BAG",
                "display_name": "T4 Bag",
            })()],
            "to_dict": lambda self: {
                "resolved": True,
                "query": "T4_BAG",
                "matches": [{"unique_name": "T4_BAG", "display_name": "T4 Bag"}],
            },
        })()
        mock_resolver.resolve.return_value = mock_result

        response = client.post(
            "/mcp/tools/call",
            json={"name": "resolve_item", "arguments": {"query": "\nT4_BAG\n(T4)\n"}},
        )

    assert response.status_code == 200
    assert response.json()["isError"] is False
    mock_resolver.resolve.assert_called_once_with("T4_BAG", limit=10)


def test_mcp_tools_call_rejects_bool_for_integer():
    """Booleans should not pass integer validation."""
    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "execute_code",
            "arguments": {"code": "1+1", "timeout": True},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is True
    assert "must be an integer" in data["content"][0]["text"]


def test_mcp_search_activities_depths_returns_activity():
    """Depths should resolve through activity search instead of item search."""
    response = client.post(
        "/mcp/tools/call",
        json={"name": "search_activities", "arguments": {"query": "depth", "limit": 5}},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    payload = data["content"][0]["text"]
    assert "The Depths" in payload


def test_mcp_search_items_includes_activity_hint_when_empty():
    """Item search should emit an activity hint for activity-like queries."""
    with patch("app.mcp.tools.gamedata.game_db.search_items", return_value=[]):
        response = client.post(
            "/mcp/tools/call",
            json={"name": "search_items", "arguments": {"query": "depth", "limit": 5}},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    payload = data["content"][0]["text"]
    assert "activity_hint" in payload
    assert "search_activities" in payload


def test_mcp_destiny_quality_bonus_returns_payload():
    with patch("app.mcp.tools.combat.destiny_db.get_quality_bonus", return_value=100):
        response = client.post(
            "/mcp/tools/call",
            json={"name": "destiny_quality_bonus", "arguments": {"quality": 4}},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False
    assert data["structuredContent"]["quality"] == 4
    assert data["structuredContent"]["ip_bonus"] == 100


def test_mcp_tools_have_descriptions():
    """Test that all tools have proper descriptions for LLM understanding."""
    response = client.post("/mcp/tools/list")
    data = response.json()

    for tool in data["tools"]:
        # Description should be meaningful, not empty
        assert len(tool["description"]) > 20

        # inputSchema properties should also have descriptions
        schema = tool["inputSchema"]
        if "properties" in schema:
            for prop_name, prop_def in schema["properties"].items():
                assert "description" in prop_def, f"Tool {tool['name']}.{prop_name} missing description"


def test_mcp_tools_include_annotations_and_optional_output_schema():
    """Tool metadata should include MCP annotations and output schemas where defined."""
    response = client.post("/mcp/tools/list")
    data = response.json()
    tools_by_name = {tool["name"]: tool for tool in data["tools"]}

    assert "annotations" in tools_by_name["market_data"]
    assert tools_by_name["market_data"]["annotations"]["readOnlyHint"] is True

    assert "outputSchema" in tools_by_name["execute_code"]
