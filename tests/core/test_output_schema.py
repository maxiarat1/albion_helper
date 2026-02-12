"""Tests for output schema definitions."""

import pytest

from app.core.schema import (
    AgentResponse,
    TextResponse,
    DataResponse,
    ActionRequest,
    ErrorResponse,
    ResponseType,
)


class TestResponseType:
    """Tests for ResponseType enum."""

    def test_values(self):
        assert ResponseType.TEXT == "text"
        assert ResponseType.DATA == "data"
        assert ResponseType.ACTION == "action"
        assert ResponseType.ERROR == "error"


class TestAgentResponseFactories:
    """Tests for AgentResponse factory methods."""

    def test_text_factory(self):
        response = AgentResponse.text("Hello, world!")
        assert isinstance(response, TextResponse)
        assert response.type == ResponseType.TEXT
        assert response.content == "Hello, world!"

    def test_text_with_metadata(self):
        response = AgentResponse.text("Hello", source="test")
        assert response.metadata == {"source": "test"}

    def test_data_factory(self):
        data = {"price": 1234, "city": "Caerleon"}
        response = AgentResponse.data(data)
        assert isinstance(response, DataResponse)
        assert response.type == ResponseType.DATA
        assert response.content == data

    def test_data_with_schema_ref(self):
        response = AgentResponse.data({"x": 1}, schema_ref="market_response")
        assert response.schema_ref == "market_response"

    def test_action_factory(self):
        response = AgentResponse.action("get_prices", {"item": "T4 Bag"})
        assert isinstance(response, ActionRequest)
        assert response.type == ResponseType.ACTION
        assert response.tool == "get_prices"
        assert response.arguments == {"item": "T4 Bag"}

    def test_error_factory(self):
        response = AgentResponse.error("Something went wrong", code="ERR_001")
        assert isinstance(response, ErrorResponse)
        assert response.type == ResponseType.ERROR
        assert response.content == "Something went wrong"
        assert response.error_code == "ERR_001"


class TestAgentResponseParsing:
    """Tests for AgentResponse.parse() method."""

    def test_parse_plain_text(self):
        response = AgentResponse.parse("Just a plain text response")
        assert isinstance(response, TextResponse)
        assert response.content == "Just a plain text response"

    def test_parse_json_tool_call(self):
        raw = '{"tool": "get_prices", "arguments": {"item": "T4 Bag"}}'
        response = AgentResponse.parse(raw)
        assert isinstance(response, ActionRequest)
        assert response.tool == "get_prices"
        assert response.arguments == {"item": "T4 Bag"}

    def test_parse_null_tool(self):
        """When tool is null, it means 'no tool needed' - treat as text."""
        raw = '{"tool": null}'
        response = AgentResponse.parse(raw)
        assert isinstance(response, TextResponse)

    def test_parse_json_data(self):
        raw = '{"price": 1234, "city": "Caerleon"}'
        response = AgentResponse.parse(raw)
        assert isinstance(response, DataResponse)
        assert response.content == {"price": 1234, "city": "Caerleon"}

    def test_parse_markdown_code_block(self):
        raw = """```json
{"tool": "compare_cities", "arguments": {"item": "T4 Leather"}}
```"""
        response = AgentResponse.parse(raw)
        assert isinstance(response, ActionRequest)
        assert response.tool == "compare_cities"

    def test_parse_with_expected_type_mismatch_logs_warning(self, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        
        raw = "Plain text"
        response = AgentResponse.parse(raw, expected=ResponseType.DATA)
        
        assert isinstance(response, TextResponse)
        assert "type mismatch" in caplog.text

    def test_parse_embedded_json(self):
        """Parse JSON embedded in surrounding text."""
        # Note: The regex extracts the first {} block, so nested objects may not work
        raw = 'Here is my response: {"price": 1234} done.'
        response = AgentResponse.parse(raw)
        assert isinstance(response, DataResponse)
        assert response.content == {"price": 1234}


class TestActionRequest:
    """Tests for ActionRequest specific behavior."""

    def test_content_synced_with_tool_args(self):
        """Content should mirror tool/arguments for consistent serialization."""
        action = ActionRequest(tool="test_tool", arguments={"a": 1})
        assert action.content == {"tool": "test_tool", "arguments": {"a": 1}}

    def test_serialization(self):
        action = AgentResponse.action("my_tool", {"x": 42})
        data = action.model_dump()
        assert data["tool"] == "my_tool"
        assert data["arguments"] == {"x": 42}


class TestErrorResponse:
    """Tests for ErrorResponse."""

    def test_error_with_code(self):
        error = ErrorResponse(content="Not found", error_code="NOT_FOUND")
        assert error.type == ResponseType.ERROR
        assert error.content == "Not found"
        assert error.error_code == "NOT_FOUND"

    def test_error_without_code(self):
        error = ErrorResponse(content="Something failed")
        assert error.error_code is None
