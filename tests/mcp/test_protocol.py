"""Tests for tool call parsing and formatting."""

from app.mcp.protocol import ToolCall, extract_tool_call, format_tool_result


class TestExtractToolCall:
    """Tests for extract_tool_call."""

    def test_plain_text_returns_no_tool(self):
        call = extract_tool_call("Just a plain answer")
        assert not call.wants_tool
        assert call.tool is None
        assert call.raw == "Just a plain answer"

    def test_tool_call_json(self):
        raw = '{"tool": "market_data", "arguments": {"item": "T4 Bag"}}'
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.tool == "market_data"
        assert call.arguments == {"item": "T4 Bag"}

    def test_null_tool_returns_no_tool(self):
        raw = '{"tool": null}'
        call = extract_tool_call(raw)
        assert not call.wants_tool
        assert call.tool is None

    def test_empty_tool_returns_no_tool(self):
        raw = '{"tool": ""}'
        call = extract_tool_call(raw)
        assert not call.wants_tool

    def test_json_in_code_block(self):
        raw = """```json
{"tool":"execute_code","arguments":{"code":"rows=[1,2,3]\\nresult=sum(rows)\\nresult","timeout":5}}
```"""
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.tool == "execute_code"
        assert call.arguments["timeout"] == 5
        assert "sum(rows)" in call.arguments["code"]

    def test_strips_tool_whitespace(self):
        raw = '{"tool": "  execute_code  ", "arguments": {"code": "1+1"}}'
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.tool == "execute_code"

    def test_non_dict_arguments_default_to_empty(self):
        raw = '{"tool": "market_data", "arguments": "bad"}'
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.arguments == {}

    def test_missing_arguments_default_to_empty(self):
        raw = '{"tool": "market_data"}'
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.arguments == {}

    def test_skips_echoed_result_json_finds_tool_call(self):
        """Model echoes an API result as JSON, then has the real tool call below."""
        raw = (
            '#### Price in Caerleon\n'
            '```json\n'
            '{"item": {"id": "T6_2H_BOW"}, "price_summary": {"best_sell": {"price": 99995}}}\n'
            '```\n'
            'Now checking Fort Sterling.\n'
            '```json\n'
            '{"tool": "market_data", "arguments": {"item": "T6_2H_BOW", "cities": ["Fort Sterling"]}}\n'
            '```'
        )
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.tool == "market_data"
        assert call.arguments["cities"] == ["Fort Sterling"]

    def test_skips_non_tool_json_in_text(self):
        """Inline JSON without a 'tool' key should not register as a tool call."""
        raw = 'The result was {"price": 50000, "city": "Caerleon"}. Done!'
        call = extract_tool_call(raw)
        assert not call.wants_tool

    def test_multiple_fenced_blocks_finds_tool(self):
        """First fenced block is data, second is the tool call."""
        raw = (
            '```json\n{"data": [1, 2, 3]}\n```\n'
            'Calling next:\n'
            '```json\n{"tool": "spell_info", "arguments": {"spell": "Multishot"}}\n```'
        )
        call = extract_tool_call(raw)
        assert call.wants_tool is True
        assert call.tool == "spell_info"


class TestToolCall:
    """Tests for ToolCall dataclass."""

    def test_wants_tool_true(self):
        call = ToolCall(tool="get_prices", arguments={})
        assert call.wants_tool is True

    def test_wants_tool_false_for_none(self):
        call = ToolCall(tool=None)
        assert call.wants_tool is False

    def test_wants_tool_false_for_empty(self):
        call = ToolCall(tool="")
        assert call.wants_tool is False


class TestFormatToolResult:
    """Tests for format_tool_result."""

    def test_success(self):
        result = format_tool_result(
            "get_prices",
            {"price": 1234, "city": "Caerleon"},
        )
        assert "\u2713 get_prices" in result
        assert '"price": 1234' in result

    def test_failure(self):
        result = format_tool_result(
            "get_prices",
            "Connection timeout",
            success=False,
        )
        assert "\u2717 get_prices failed:" in result
        assert "Connection timeout" in result

    def test_execute_code_result_filtered(self):
        raw_result = {
            "success": True,
            "result": 42,
            "result_type": "int",
            "output": "",
            "error": None,
            "observation": "ok",
            "extra_field": "should be dropped",
        }
        result = format_tool_result("execute_code", raw_result)
        assert '"extra_field"' not in result
        assert '"result": 42' in result

    def test_market_data_strips_raw_data(self):
        raw_result = {
            "item": {"id": "T6_BAG"},
            "data": [{"location": "Caerleon", "sell_price_min": 50000}] * 29,
            "summary": {"best_sell": {"location": "Caerleon", "price": 50000}},
            "freshness": {"total_entries": 29},
        }
        result = format_tool_result("market_data", raw_result)
        assert '"data"' not in result
        assert '"summary"' in result
        assert '"best_sell"' in result
