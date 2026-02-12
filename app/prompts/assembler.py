"""JIT (Just-In-Time) Prompt Assembly System.

Implements the State-Reflective workflow using structured schemas:
1. RE-READ mutable files on each request (no stale cache)
2. Parse YAML frontmatter for metadata (priority, output_contract, etc.)
3. Assemble layered prompts in priority order (identity first)
4. Support self-modification by always re-reading mutable files

Prompt Layers (assembly order — identity first, tools last):
1. SOUL.md (100): Core personality — WHO the agent is
2. MEMORY.md (90): Persistent facts — WHAT it remembers
3. SKILLS.md (80): Learned playbooks — HOW to handle known tasks
4. USER.md (70): User preferences — WHO it is talking to
5. CONFIG.md (60): Behavior settings — HOW to respond
6. tasks/*.md (50): Scenario instructions — WHAT to do now
7. Tools — WHAT capabilities are available

Usage:
    assembler = PromptAssembler()
    result = assembler.assemble(tools=registry.list_tools())
    print(result.system_prompt)  # Full assembled prompt
    print(result.output_contract)  # Expected response format
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.schema import PromptDocument, PromptMeta, PromptType
from app.core.schema.prompt_schema import OutputContract

logger = logging.getLogger(__name__)

# Default prompts directory (relative to this file)
DEFAULT_PROMPTS_DIR = Path(__file__).parent

# Files that are mutable by the agent (always re-read, never cached)
MUTABLE_TYPES = {PromptType.SOUL, PromptType.MEMORY, PromptType.SKILLS, PromptType.USER, PromptType.CONFIG}
_EMPTY_CONTENT_PATTERNS = (
    re.compile(r"<!--.*?-->", re.DOTALL),
    re.compile(r"</?[^>\n]+>"),
    re.compile(r"\(not set[^)]*\)"),
    re.compile(r"\(No [^)]*\)"),
    re.compile(r"#.*"),
    re.compile(r"-\s*\*\*[^*]+\*\*:\s*"),
    re.compile(r"\*Last (modified|updated):.*\*"),
    re.compile(r"---"),
)

_PLACEHOLDER_VALUES = {
    "(not set)",
    "(no facts recorded yet)",
    "(no sessions recorded yet)",
    "(no active context)",
    "(no skills learned yet)",
    "(no skills)",
}

# Regex to match <slot ...>...<value>...</value>...</slot> blocks
_SLOT_PATTERN = re.compile(
    r'<slot\s+id="(?P<id>[^"]+)"(?:\s+hint="(?P<hint>[^"]*)")?\s*>\s*'
    r"<value>(?P<value>.*?)</value>\s*</slot>",
    re.DOTALL,
)


def _render_natural(content: str) -> str:
    """Convert XML slot structures to natural markdown prose.

    - Empty / placeholder slots are dropped entirely.
    - Simple text values become ``- **Label**: value`` bullets.
    - ``<entry timestamp="...">`` elements become timestamped list items.
    - ``<skill>`` elements become titled numbered-step blocks.
    - Content without XML slots passes through unchanged.
    """
    # Strip HTML comments first
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

    def _replace_slot(match: re.Match[str]) -> str:
        slot_id = match.group("id")
        hint = match.group("hint") or slot_id
        raw_value = match.group("value").strip()

        # Drop empty / placeholder slots
        normalised = re.sub(r"\s+", " ", raw_value.lower())
        if not raw_value or normalised in _PLACEHOLDER_VALUES:
            return ""

        # --- Attempt structured XML parsing ---
        # Wrap in a root so ET can parse fragments
        try:
            root = ET.fromstring(f"<root>{raw_value}</root>")
        except ET.ParseError:
            # Plain text value — render as a bullet
            label = _slot_label(hint)
            return f"- **{label}**: {raw_value}"

        # Check for <entry> children (memory-style)
        entries = root.findall("entry")
        if entries:
            label = _slot_label(hint)
            lines = [f"**{label}**:"]
            for entry in entries:
                ts = entry.get("timestamp", "")
                text = (entry.text or "").strip()
                lines.append(f"- [{ts}] {text}" if ts else f"- {text}")
            return "\n".join(lines)

        # Check for <skill> children (skills-style)
        skills = root.findall("skill")
        if skills:
            blocks: list[str] = []
            for skill in skills:
                name = _el_text(skill, "name")
                desc = _el_text(skill, "description")
                learned = _el_text(skill, "learned")
                steps_el = skill.find("steps")
                header = f"**{name}**"
                if desc:
                    header += f" — {desc}"
                if learned:
                    header += f" (learned {learned})"
                block_lines = [header]
                if steps_el is not None:
                    for step in steps_el.findall("step"):
                        idx = step.get("index", "")
                        text = (step.text or "").strip()
                        block_lines.append(f"{idx}. {text}" if idx else f"- {text}")
                blocks.append("\n".join(block_lines))
            return "\n\n".join(blocks)

        # Fallback: unknown XML children — render as bullet
        label = _slot_label(hint)
        return f"- **{label}**: {raw_value}"

    result = _SLOT_PATTERN.sub(_replace_slot, content)
    # Collapse excessive blank lines left behind by removed slots
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def _slot_label(hint: str) -> str:
    """Turn a slot hint or id into a human-readable label."""
    return hint.replace("_", " ").strip().capitalize()


def _el_text(parent: ET.Element, tag: str) -> str:
    """Safely extract text from a child element."""
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


@dataclass
class PromptLayer:
    """A single prompt layer with its content and metadata."""

    name: str
    content: str
    source: Path | None = None
    meta: PromptMeta | None = None

    @property
    def priority(self) -> int:
        """Get priority from metadata or default."""
        return self.meta.priority if self.meta else 50

    def __bool__(self) -> bool:
        return bool(self.content.strip())


@dataclass
class AssembledPrompt:
    """Result of prompt assembly with metadata."""

    system_prompt: str
    layers_used: list[str] = field(default_factory=list)
    task: str | None = None
    tool_count: int = 0
    output_contract: OutputContract = OutputContract.ANY

    def to_message(self) -> dict[str, str]:
        """Convert to message format for LLM."""
        return {"role": "system", "content": self.system_prompt}


class PromptAssembler:
    """Assembles system prompts from modular layers.

    Implements the State-Reflective workflow with structured schemas:
    1. Parse YAML frontmatter for metadata
    2. Order layers by priority (higher = loaded later)
    3. Always RE-READ mutable files (SOUL, MEMORY, etc.)
    4. Cache read-only files (tasks/*) for performance
    """

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self.prompts_dir = prompts_dir or DEFAULT_PROMPTS_DIR
        self._cache: dict[str, PromptDocument] = {}

    def _load_file(
        self,
        relative_path: str,
        required: bool = False,
    ) -> PromptLayer:
        """Load a prompt file from the prompts directory.

        Automatically parses YAML frontmatter and caches immutable files.

        Args:
            relative_path: Path relative to prompts directory
            required: If True, raise error when file not found
        """
        file_path = self.prompts_dir / relative_path
        cache_key = str(file_path)

        # Try cache first for immutable files
        if cache_key in self._cache:
            doc = self._cache[cache_key]
            return PromptLayer(
                name=relative_path,
                content=doc.content,
                source=doc.source,
                meta=doc.meta,
            )

        if not file_path.exists():
            if required:
                raise FileNotFoundError(f"Required prompt file not found: {file_path}")
            logger.debug("Optional prompt file not found: %s", file_path)
            return PromptLayer(name=relative_path, content="")

        try:
            doc = PromptDocument.from_file(file_path)

            # Only cache immutable files
            if doc.meta.type not in MUTABLE_TYPES:
                self._cache[cache_key] = doc

            return PromptLayer(
                name=relative_path,
                content=doc.content,
                source=doc.source,
                meta=doc.meta,
            )
        except Exception as exc:
            logger.error("Failed to load prompt file %s: %s", file_path, exc)
            if required:
                raise
            return PromptLayer(name=relative_path, content="")

    def _format_tools_menu(self, tools: list[dict[str, Any]]) -> str:
        """Format available tools as a menu for the system prompt."""
        if not tools:
            return ""

        lines = [
            "## Tool Protocol",
            "",
            "To call a tool, respond with ONLY this JSON — nothing else:",
            '{"tool": "tool_name", "arguments": {"param": "value"}}',
            "",
            "Rules:",
            "- ONE tool call per response. Never multiple.",
            "- No text, markdown, or explanation alongside a tool call.",
            "- Never echo or repeat tool results as JSON.",
            "- After receiving a result, either call another tool or give your final answer in plain text.",
            "- Use exact parameter names from the schemas below.",
            "- NEVER fill in optional parameters the user didn't specify — omitting them gives broader, more useful results. Guessing defaults narrows the search and causes missed data.",
            "",
        ]
        for tool in tools:
            name = tool.get("name", "unknown")
            description = tool.get("description", "No description")
            lines.append(f"### `{name}`")
            lines.append(f"{description}")
            lines.append("")

            # Add input schema summary if available
            schema = tool.get("inputSchema", {})
            properties = schema.get("properties", {})
            required = set(schema.get("required", []))

            if properties:
                lines.append("**Parameters:**")
                for prop_name, prop_def in properties.items():
                    prop_type = prop_def.get("type", "any")
                    prop_desc = prop_def.get("description", "")
                    req_marker = " *(required)*" if prop_name in required else " *(optional — omit if not specified by user)*"
                    lines.append(f"- `{prop_name}` ({prop_type}){req_marker}: {prop_desc}")
                lines.append("")

        return "\n".join(lines)

    def assemble(
        self,
        *,
        task: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        include_memory: bool = True,
        include_skills: bool = True,
        include_user: bool = True,
        include_config: bool = True,
    ) -> AssembledPrompt:
        """Assemble the final system prompt from all layers.

        Assembly order (identity first, tools last):
        1. SOUL.md - Core personality (WHO the agent is)
        2. MEMORY.md - Persistent facts (WHAT it remembers)
        3. SKILLS.md - Learned playbooks (HOW to handle known tasks)
        4. USER.md - User preferences (WHO it is talking to)
        5. CONFIG.md - Behavior settings (HOW to respond)
        6. tasks/*.md - Scenario instructions (WHAT to do now)
        7. Tools menu - Dynamic from registry
        """
        layers: list[PromptLayer] = []
        layers_used: list[str] = []

        # 1. SOUL - Core Personality (always included)
        soul = self._load_file("SOUL.md", required=True)
        if soul:
            layers.append(soul)
            layers_used.append("soul")

        # 2. MEMORY - Persistent Facts
        if include_memory:
            memory = self._load_file("MEMORY.md")
            if memory and not self._is_empty_content(memory.content):
                layers.append(memory)
                layers_used.append("memory")

        # 3. SKILLS - Learned Playbooks
        if include_skills:
            skills = self._load_file("SKILLS.md")
            if skills and not self._is_empty_content(skills.content):
                layers.append(skills)
                layers_used.append("skills")

        # 4. USER - User Preferences
        if include_user:
            user = self._load_file("USER.md")
            if user and not self._is_empty_content(user.content):
                layers.append(user)
                layers_used.append("user")

        # 5. CONFIG - Behavior Settings
        if include_config:
            config = self._load_file("CONFIG.md")
            if config and not self._is_empty_content(config.content):
                layers.append(config)
                layers_used.append("config")

        # 6. Task Layer - Load explicit task if provided
        output_contract = OutputContract.ANY
        if task:
            task_file = f"tasks/{task}.md"
            task_layer = self._load_file(task_file)
            if task_layer:
                layers.append(task_layer)
                layers_used.append(f"task:{task}")
                if task_layer.meta:
                    output_contract = task_layer.meta.output_contract

        # Sort layers by priority — highest first (identity before rules)
        layers.sort(key=lambda l: l.priority, reverse=True)

        # Build sections from sorted layers (render XML to natural prose)
        sections: list[str] = []
        for layer in layers:
            rendered = _render_natural(layer.content)
            if rendered.strip():
                if sections:
                    sections.append("")  # blank line between layers
                sections.append(rendered)

        # 7. Operational Layer - Tools menu (always last)
        tool_list = tools or []
        if tool_list:
            sections.append("")  # blank line before tools
            sections.append(self._format_tools_menu(tool_list))
            layers_used.append("tools")

        return AssembledPrompt(
            system_prompt="\n".join(sections).strip(),
            layers_used=layers_used,
            task=task,
            tool_count=len(tool_list),
            output_contract=output_contract,
        )

    def _is_empty_content(self, content: str) -> bool:
        """Check if content is effectively empty (just template markers)."""
        cleaned = content
        for pattern in _EMPTY_CONTENT_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        return not cleaned.strip()

    def clear_cache(self) -> None:
        """Clear the prompt file cache."""
        self._cache.clear()

    def reload(self) -> None:
        """Reload all cached prompt files."""
        self.clear_cache()


# Singleton instance for easy access
default_assembler = PromptAssembler()
