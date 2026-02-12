"""MCP tools for agent self-modification.

Provides tools for the agent to read and modify its own state:
- Read its personality, memory, skills, and configuration
- Update its soul/personality based on user feedback
- Save persistent memories from conversations
- Learn and store reusable skill playbooks
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mcp.registry import Param, tool
from app.mcp.tool_templates import MUTATING_LOCAL, READ_ONLY_LOCAL

logger = logging.getLogger(__name__)

# Prompts directory (relative to this file)
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Allowed files for self-modification (safety constraint)
ALLOWED_FILES = {
    "SOUL.md": "Core personality and behavior",
    "MEMORY.md": "Persistent facts and context",
    "SKILLS.md": "Learned playbooks and recipes",
    "USER.md": "User preferences and profile",
    "CONFIG.md": "AI behavior settings",
}

_PLACEHOLDER_VALUES = {
    "(not set)",
    "(no facts recorded yet)",
    "(no sessions recorded yet)",
    "(no active context)",
    "(no skills learned yet)",
    "(no skills)",
}


def _get_file_path(filename: str) -> Path:
    """Get the full path for a prompt file."""
    if filename not in ALLOWED_FILES:
        raise ValueError(f"Access denied: '{filename}' is not modifiable. Allowed: {list(ALLOWED_FILES.keys())}")
    return PROMPTS_DIR / filename


def _backup_file(path: Path) -> None:
    """Create a backup of a file before modification."""
    if path.exists():
        backup_path = path.with_suffix(".md.bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Created backup: %s", backup_path)


def _add_timestamp(content: str) -> str:
    """Update the 'Last modified' timestamp in content."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if "*Last modified:" in content or "*Last updated:" in content:
        content = re.sub(
            r"\*Last (modified|updated):.*\*",
            f"*Last modified: {timestamp}*",
            content,
        )
    return content


def _is_placeholder_value(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized in _PLACEHOLDER_VALUES


def _append_to_slot_value(content: str, *, slot_id: str, entry: str) -> str | None:
    """Append an XML-like entry to a slot value block.

    Returns updated content when the slot exists, otherwise None.
    """
    pattern = re.compile(
        rf'(<slot\s+id="{re.escape(slot_id)}"[^>]*>\s*<value>)(.*?)(</value>\s*</slot>)',
        re.DOTALL,
    )
    match = pattern.search(content)
    if not match:
        return None

    prefix = match.group(1)
    existing_value = match.group(2)
    suffix = match.group(3)
    existing_text = existing_value.strip()

    if not existing_text or _is_placeholder_value(existing_text):
        new_value = f"\n{entry}\n  "
    else:
        new_value = f"\n{existing_text}\n{entry}\n  "

    return content[:match.start()] + prefix + new_value + suffix + content[match.end():]


def _append_to_markdown_section(content: str, *, section_header: str, entry: str) -> str:
    """Fallback appender for legacy markdown templates."""
    if section_header in content:
        pattern = rf"({re.escape(section_header)}.*?)(\n## |\n---|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            section_end = match.end(1)
            return content[:section_end] + entry + content[section_end:]
        return content + entry
    return content + f"\n{section_header}\n{entry}\n"


def _escape_xml_text(value: str) -> str:
    """Escape text intended for XML-like element bodies."""
    return html.escape(value, quote=True)


def _format_memory_entry(*, timestamp: str, content: str) -> str:
    escaped_content = _escape_xml_text(content)
    return f'    <entry timestamp="{timestamp}">{escaped_content}</entry>'


def _format_skill_entry(*, name: str, description: str, steps: list[str], learned_date: str) -> str:
    escaped_name = _escape_xml_text(name)
    escaped_description = _escape_xml_text(description)
    step_lines = "\n".join(
        f'        <step index="{index}">{_escape_xml_text(step)}</step>'
        for index, step in enumerate(steps, start=1)
    )
    return (
        "    <skill>\n"
        f"      <name>{escaped_name}</name>\n"
        f"      <description>{escaped_description}</description>\n"
        "      <steps>\n"
        f"{step_lines}\n"
        "      </steps>\n"
        f"      <learned>{learned_date}</learned>\n"
        "    </skill>"
    )


@tool(
    name="read_self",
    description="Read the agent's own state files (SOUL.md, MEMORY.md, SKILLS.md, USER.md, CONFIG.md).",
    params=[
        Param("file", "string", "Which state file to read", required=True, enum=list(ALLOWED_FILES.keys())),
    ],
    annotations=READ_ONLY_LOCAL,
    visibility="admin",
)
async def read_self(args: dict[str, Any]) -> dict[str, Any]:
    """Read the agent's own state files."""
    filename = args["file"]
    path = _get_file_path(filename)

    if not path.exists():
        return {
            "file": filename,
            "exists": False,
            "content": None,
            "description": ALLOWED_FILES.get(filename),
        }

    content = path.read_text(encoding="utf-8")
    return {
        "file": filename,
        "exists": True,
        "content": content,
        "description": ALLOWED_FILES.get(filename),
        "size_bytes": len(content.encode("utf-8")),
    }


@tool(
    name="update_soul",
    description="Modify the agent's personality/behavior in SOUL.md. Use when the user asks to change tone, style, or behavior permanently.",
    params=[
        Param("section", "string", "Markdown section heading to update. If omitted, the full file content is replaced."),
        Param("content", "string", "New content for the section or entire file", required=True, min_length=1),
        Param("reason", "string", "Why this change is being made (for logging)"),
    ],
    annotations=MUTATING_LOCAL,
    visibility="admin",
)
async def update_soul(args: dict[str, Any]) -> dict[str, Any]:
    """Update the agent's personality/soul file."""
    section = args.get("section")
    new_content = args["content"]
    reason = args.get("reason", "No reason provided")

    path = _get_file_path("SOUL.md")
    _backup_file(path)

    current_content = path.read_text(encoding="utf-8") if path.exists() else ""

    if section:
        section_pattern = rf"(## {re.escape(section)}.*?)(?=\n## |\n---|\Z)"
        match = re.search(section_pattern, current_content, re.DOTALL)

        if match:
            new_section = f"## {section}\n\n{new_content}\n"
            updated_content = current_content[:match.start()] + new_section + current_content[match.end():]
        else:
            updated_content = current_content.rstrip() + f"\n\n## {section}\n\n{new_content}\n"
    else:
        updated_content = new_content

    updated_content = _add_timestamp(updated_content)
    path.write_text(updated_content, encoding="utf-8")

    logger.info("Updated SOUL.md: %s", reason)

    return {
        "success": True,
        "file": "SOUL.md",
        "section": section,
        "reason": reason,
        "backup_created": True,
    }


@tool(
    name="save_memory",
    description="Store a fact or context in persistent memory (MEMORY.md) across sessions.",
    params=[
        Param("category", "string", "Category: user_facts, session_summary, or active_context", required=True, enum=["user_facts", "session_summary", "active_context"]),
        Param("content", "string", "The fact or context to save", required=True, min_length=1),
    ],
    annotations=MUTATING_LOCAL,
    visibility="admin",
)
async def save_memory(args: dict[str, Any]) -> dict[str, Any]:
    """Save a fact or context to persistent memory."""
    category = args["category"]
    content = args["content"]

    path = _get_file_path("MEMORY.md")
    _backup_file(path)

    current_content = path.read_text(encoding="utf-8") if path.exists() else ""

    slot_map = {
        "user_facts": "user_facts",
        "session_summary": "session_summaries",
        "active_context": "active_context",
    }
    section_map = {
        "user_facts": "## User Facts",
        "session_summary": "## Session Summaries",
        "active_context": "## Active Context",
    }
    slot_id = slot_map.get(category)
    section_header = section_map.get(category)
    if not slot_id or not section_header:
        raise ValueError(f"Invalid category: {category}. Use: {list(slot_map.keys())}")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    xml_entry = _format_memory_entry(timestamp=timestamp, content=content)
    updated_content = _append_to_slot_value(current_content, slot_id=slot_id, entry=xml_entry)

    # Fallback for older markdown templates that do not use slot/value tags.
    if updated_content is None:
        markdown_entry = f"\n- [{timestamp}] {content}"
        updated_content = _append_to_markdown_section(
            current_content,
            section_header=section_header,
            entry=markdown_entry,
        )

    updated_content = _add_timestamp(updated_content)
    path.write_text(updated_content, encoding="utf-8")

    logger.info("Saved to MEMORY.md [%s]: %s...", category, content[:50])

    return {
        "success": True,
        "file": "MEMORY.md",
        "category": category,
        "content_preview": content[:100],
    }


@tool(
    name="learn_skill",
    description="Save a reusable playbook/recipe to SKILLS.md. Use after completing a complex multi-step task.",
    params=[
        Param("name", "string", "Concise skill title that uniquely identifies the workflow", required=True, min_length=1),
        Param("description", "string", "What this skill does", required=True, min_length=1),
        Param("steps", "array", "Steps to perform this skill", items_type="string", required=True),
    ],
    annotations=MUTATING_LOCAL,
    visibility="admin",
)
async def learn_skill(args: dict[str, Any]) -> dict[str, Any]:
    """Save a learned skill/playbook to SKILLS.md."""
    name = args["name"]
    description = args["description"]
    steps = args["steps"]

    path = _get_file_path("SKILLS.md")
    _backup_file(path)

    current_content = path.read_text(encoding="utf-8") if path.exists() else ""

    timestamp = datetime.now().strftime("%Y-%m-%d")
    xml_skill_entry = _format_skill_entry(
        name=name,
        description=description,
        steps=steps,
        learned_date=timestamp,
    )
    updated_content = _append_to_slot_value(
        current_content,
        slot_id="skill_records",
        entry=xml_skill_entry,
    )

    # Fallback for older markdown templates that do not use slot/value tags.
    if updated_content is None:
        steps_formatted = "\n".join(f"{i+1}. {step}" for i, step in enumerate(steps))
        skill_entry = f"""
## {name}

**Description**: {description}

**Steps**:
{steps_formatted}

**Learned**: {timestamp}
"""
        if "## Available Skills" in current_content:
            if "(No skills learned yet)" in current_content:
                updated_content = current_content.replace("(No skills learned yet)", skill_entry)
            else:
                insert_pos = current_content.find("## Available Skills") + len("## Available Skills")
                updated_content = current_content[:insert_pos] + "\n" + skill_entry + current_content[insert_pos:]
        else:
            updated_content = current_content + f"\n## Available Skills\n{skill_entry}"

    updated_content = _add_timestamp(updated_content)
    path.write_text(updated_content, encoding="utf-8")

    logger.info("Learned skill: %s", name)

    return {
        "success": True,
        "file": "SKILLS.md",
        "skill_name": name,
        "step_count": len(steps),
    }
