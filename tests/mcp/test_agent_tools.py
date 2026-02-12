"""Tests for agent self-modification tools."""

import re
import pytest
from pathlib import Path
import tempfile
import shutil

from fastapi.testclient import TestClient
import app.mcp.router as mcp_router_module
import app.mcp.tools.agent as agent_tools_module
from app.web.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def enable_admin_tools(monkeypatch):
    monkeypatch.setattr(mcp_router_module, "_ALLOW_ADMIN_TOOLS", True)


@pytest.fixture
def temp_prompts_dir():
    """Create a temporary prompts directory for testing."""
    temp_dir = tempfile.mkdtemp()

    # Create test state files
    (Path(temp_dir) / "SOUL.md").write_text("# Test Soul\n\nYou are a test agent.\n\n---\n*Last modified: Never*")
    (Path(temp_dir) / "MEMORY.md").write_text(
        "# Memory\n\n"
        "## User Facts\n\n"
        '<slot id="user_facts" hint="facts">\n'
        "  <value>(not set)</value>\n"
        "</slot>\n\n"
        "## Session Summaries\n\n"
        '<slot id="session_summaries" hint="summaries">\n'
        "  <value>(not set)</value>\n"
        "</slot>\n\n"
        "## Active Context\n\n"
        '<slot id="active_context" hint="context">\n'
        "  <value>(not set)</value>\n"
        "</slot>\n\n"
        "---\n"
        "*Last updated: Never*"
    )
    (Path(temp_dir) / "SKILLS.md").write_text(
        "# Skills\n\n"
        "## Available Skills\n\n"
        '<slot id="skill_records" hint="skills">\n'
        "  <value>(not set)</value>\n"
        "</slot>\n\n"
        "---\n"
        "*Last updated: Never*"
    )
    (Path(temp_dir) / "USER.md").write_text("# User\n\n(not set)")
    (Path(temp_dir) / "CONFIG.md").write_text("# Config\n\n- verbosity: concise")

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


def test_read_self_soul():
    """Test reading the SOUL.md file."""
    response = client.post(
        "/mcp/tools/call",
        json={"name": "read_self", "arguments": {"file": "SOUL.md"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is False

    import json
    content = json.loads(data["content"][0]["text"])
    assert content["file"] == "SOUL.md"
    assert content["exists"] is True
    assert "Albion Helper" in content["content"]


def test_read_self_invalid_file():
    """Test that reading non-allowed files fails."""
    response = client.post(
        "/mcp/tools/call",
        json={"name": "read_self", "arguments": {"file": "../../etc/passwd"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["isError"] is True
    assert "Invalid arguments" in data["content"][0]["text"]


def test_mcp_tools_list_includes_agent_tools():
    """Test that MCP tools list includes all agent tools."""
    response = client.post("/mcp/tools/list", json={"includeAdmin": True})

    assert response.status_code == 200
    data = response.json()

    tool_names = [t["name"] for t in data["tools"]]

    # All agent tools should be registered
    assert "read_self" in tool_names
    assert "update_soul" in tool_names
    assert "save_memory" in tool_names
    assert "learn_skill" in tool_names


def test_save_memory_uses_slot_format(temp_prompts_dir, monkeypatch):
    monkeypatch.setattr(agent_tools_module, "PROMPTS_DIR", Path(temp_prompts_dir))

    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "save_memory",
            "arguments": {
                "category": "user_facts",
                "content": "Prefers Martlock & Warbow",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["isError"] is False

    memory_content = (Path(temp_prompts_dir) / "MEMORY.md").read_text(encoding="utf-8")
    assert '<slot id="user_facts"' in memory_content
    assert '<entry timestamp="' in memory_content
    assert "Prefers Martlock &amp; Warbow" in memory_content
    user_facts_match = re.search(
        r'<slot id="user_facts"[^>]*>\s*<value>(.*?)</value>\s*</slot>',
        memory_content,
        re.DOTALL,
    )
    assert user_facts_match is not None
    assert "(not set)" not in user_facts_match.group(1)
    assert "*Last modified:" in memory_content


def test_learn_skill_uses_slot_format(temp_prompts_dir, monkeypatch):
    monkeypatch.setattr(agent_tools_module, "PROMPTS_DIR", Path(temp_prompts_dir))

    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "learn_skill",
            "arguments": {
                "name": "Bow Progression Planner",
                "description": "Plan weapon fame path across available budgets",
                "steps": [
                    "Collect current specs and tier comfort",
                    "Compare fame efficiency by activity",
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["isError"] is False

    skills_content = (Path(temp_prompts_dir) / "SKILLS.md").read_text(encoding="utf-8")
    assert '<slot id="skill_records"' in skills_content
    assert "<skill>" in skills_content
    assert "<name>Bow Progression Planner</name>" in skills_content
    assert '<step index="1">Collect current specs and tier comfort</step>' in skills_content
    assert '<step index="2">Compare fame efficiency by activity</step>' in skills_content
    assert "<value>(not set)</value>" not in skills_content
    assert "*Last modified:" in skills_content
