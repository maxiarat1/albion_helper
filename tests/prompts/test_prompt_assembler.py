"""Tests for the JIT Prompt Assembly system."""

import pytest

from app.prompts import PromptAssembler, AssembledPrompt


@pytest.fixture
def assembler():
    """Create a fresh assembler instance for each test."""
    return PromptAssembler()


def test_assembler_loads_soul(assembler):
    """Test that SOUL.md is always loaded."""
    result = assembler.assemble()

    assert "soul" in result.layers_used
    assert "Albion Helper" in result.system_prompt


def test_assembler_includes_tools_menu(assembler):
    """Test that tools are formatted into the prompt."""
    mock_tools = [
        {
            "name": "test_tool",
            "description": "A test tool for testing",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "First argument"},
                },
                "required": ["arg1"],
            },
        }
    ]

    result = assembler.assemble(tools=mock_tools)

    assert "tools" in result.layers_used
    assert result.tool_count == 1
    assert "test_tool" in result.system_prompt
    assert "A test tool for testing" in result.system_prompt


def test_assembler_tools_menu_includes_protocol(assembler):
    mock_tools = [
        {
            "name": "test_tool",
            "description": "A test tool for testing",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    result = assembler.assemble(tools=mock_tools)
    assert "ONE tool call per response" in result.system_prompt
    assert "exact parameter names" in result.system_prompt.lower()


def test_assembler_includes_config_content(assembler):
    result = assembler.assemble()
    assert "config" in result.layers_used
    assert "# Response Settings" in result.system_prompt


def test_assembler_skips_placeholder_layers(assembler):
    result = assembler.assemble()
    assert "memory" not in result.layers_used
    assert "skills" not in result.layers_used
    assert "user" not in result.layers_used


def test_assembler_explicit_task_without_builtin_template(assembler):
    """Explicit task names are preserved even when no bundled task file exists."""
    result = assembler.assemble(task="market_lookup")

    assert result.task == "market_lookup"
    assert "task:market_lookup" not in result.layers_used


def test_assembler_no_task_by_default(assembler):
    """Test that no task is loaded when not specified."""
    result = assembler.assemble()

    assert result.task is None


def test_assembler_returns_assembled_prompt(assembler):
    """Test that result has correct structure."""
    result = assembler.assemble()

    assert isinstance(result, AssembledPrompt)
    assert isinstance(result.system_prompt, str)
    assert isinstance(result.layers_used, list)


def test_assembler_missing_task_file_not_cached(assembler):
    """Missing task templates should not populate cache entries."""
    assembler.assemble(task="market_lookup")
    task_cached = any("tasks/market_lookup.md" in key for key in assembler._cache)
    assert not task_cached


def test_assembler_clear_cache(assembler):
    """Test cache clearing."""
    assembler._cache["dummy"] = object()
    assert len(assembler._cache) > 0

    assembler.clear_cache()
    assert len(assembler._cache) == 0


def test_assembler_to_message(assembler):
    """Test conversion to message format."""
    result = assembler.assemble()
    message = result.to_message()

    assert message["role"] == "system"
    assert message["content"] == result.system_prompt


def test_mutable_files_bypass_cache(assembler):
    """Test that mutable files (SOUL, MEMORY, etc.) are not cached."""
    result = assembler.assemble()
    
    # SOUL.md should not be in cache (it's mutable)
    soul_cached = any("SOUL.md" in key for key in assembler._cache.keys())
    assert not soul_cached, "SOUL.md should not be cached"


def test_assembler_includes_tool_protocol_in_soul(assembler):
    """Test that SOUL.md includes tool usage guidance."""
    result = assembler.assemble()

    # Should mention how to use tools (resolve items first, fetch data, etc.)
    assert "Resolve items first" in result.system_prompt or "resolve_item" in result.system_prompt


# --- _render_natural tests ---

from app.prompts.assembler import _render_natural


def test_render_natural_strips_empty_slots():
    """Empty/placeholder slots should produce no output."""
    content = '## Preferences\n\n<slot id="cities" hint="Preferred cities">\n  <value>(not set)</value>\n</slot>\n'
    result = _render_natural(content)
    assert "<slot" not in result
    assert "<value>" not in result
    assert "(not set)" not in result


def test_render_natural_converts_populated_slots():
    """Populated text slots become markdown bullets."""
    content = '<slot id="cities" hint="Preferred cities">\n  <value>Martlock, Bridgewatch</value>\n</slot>'
    result = _render_natural(content)
    assert "**Preferred cities**" in result
    assert "Martlock, Bridgewatch" in result
    assert "<slot" not in result


def test_render_natural_converts_entries():
    """Memory-style <entry> elements become timestamped list items."""
    content = (
        '<slot id="user_facts" hint="Persistent player facts">\n'
        "  <value>\n"
        '    <entry timestamp="2026-02-10 14:30">Prefers Warbow</entry>\n'
        '    <entry timestamp="2026-02-11 09:15">Has 5M silver</entry>\n'
        "  </value>\n"
        "</slot>"
    )
    result = _render_natural(content)
    assert "[2026-02-10 14:30] Prefers Warbow" in result
    assert "[2026-02-11 09:15] Has 5M silver" in result
    assert "<entry" not in result
    assert "<slot" not in result


def test_render_natural_converts_skills():
    """Skill-style <skill> elements become titled numbered-step blocks."""
    content = (
        '<slot id="skill_records" hint="Reusable workflows">\n'
        "  <value>\n"
        "    <skill>\n"
        "      <name>Bow Planner</name>\n"
        "      <description>Plan weapon fame</description>\n"
        "      <steps>\n"
        '        <step index="1">Collect specs</step>\n'
        '        <step index="2">Compare efficiency</step>\n'
        "      </steps>\n"
        "      <learned>2026-02-01</learned>\n"
        "    </skill>\n"
        "  </value>\n"
        "</slot>"
    )
    result = _render_natural(content)
    assert "**Bow Planner**" in result
    assert "Plan weapon fame" in result
    assert "1. Collect specs" in result
    assert "2. Compare efficiency" in result
    assert "(learned 2026-02-01)" in result
    assert "<skill>" not in result


def test_render_natural_passthrough_plain_markdown():
    """Content without XML slots passes through unchanged."""
    content = "# Albion Helper\n\nI am a game companion.\n\n**Direct.** Lead with the conclusion."
    result = _render_natural(content)
    assert result.strip() == content.strip()


def test_render_natural_strips_html_comments():
    """HTML comments are removed."""
    content = "# Title\n\n<!-- this is a comment -->\n\nVisible text."
    result = _render_natural(content)
    assert "this is a comment" not in result
    assert "Visible text." in result


def test_assembled_prompt_has_no_xml_tags(assembler):
    """End-to-end: assembled prompt must not contain XML slot tags."""
    result = assembler.assemble()
    import re
    xml_tags = re.findall(r"</?(?:slot|value|entry|skill|step|name|description|learned|steps)[^>]*>", result.system_prompt)
    assert xml_tags == [], f"XML tags found in system prompt: {xml_tags}"


def test_soul_appears_before_config(assembler):
    """SOUL (identity) must appear before CONFIG (behavior rules) in the prompt."""
    result = assembler.assemble()
    soul_pos = result.system_prompt.find("Albion Helper")
    config_pos = result.system_prompt.find("Response Settings")
    assert soul_pos >= 0, "SOUL content not found"
    assert config_pos >= 0, "CONFIG content not found"
    assert soul_pos < config_pos, f"SOUL ({soul_pos}) should appear before CONFIG ({config_pos})"

