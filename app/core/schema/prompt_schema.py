"""Prompt schema definitions for structured prompt files.

Provides YAML frontmatter parsing and prompt document structure:
- PromptMeta: Metadata parsed from YAML frontmatter
- PromptDocument: Complete parsed prompt with content and metadata

Usage:
    doc = PromptDocument.from_file(Path("SOUL.md"))
    print(doc.meta.priority)  # Assembly order
    print(doc.content)        # Prompt body
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

class PromptType(StrEnum):
    """Types of prompt documents."""

    SOUL = "soul"        # Core personality
    TASK = "task"        # Task-specific instructions
    MEMORY = "memory"    # Persistent facts
    CONFIG = "config"    # User/system configuration
    SKILLS = "skills"    # Learned playbooks
    USER = "user"        # User preferences


class OutputContract(StrEnum):
    """Expected output format for a prompt context."""

    TEXT = "text"        # Free-form text response
    DATA = "data"        # Structured JSON data
    ACTION = "action"    # Tool call expected
    ANY = "any"          # No specific format expected


class PromptMeta(BaseModel):
    """Metadata from YAML frontmatter in prompt files.

    Attributes:
        version: Schema version for forward compatibility
        type: Prompt document type (soul, task, memory, etc.)
        mutable: Whether the agent can modify this file
        priority: Assembly order (higher = loaded later, overrides earlier)
        output_contract: Expected response format when this prompt is active
        response_schema: Reference to JSON schema for data responses
        tags: Categorization tags for filtering/grouping
    """

    version: str = Field(default="1.0", description="Schema version")
    type: PromptType = Field(default=PromptType.SOUL, description="Document type")
    mutable: bool = Field(default=True, description="Whether agent can modify")
    priority: int = Field(
        default=50, description="Assembly order (higher = later)"
    )
    output_contract: OutputContract = Field(
        default=OutputContract.ANY, description="Expected response format"
    )
    response_schema: str | None = Field(
        default=None, description="JSON schema reference for data responses"
    )
    tags: list[str] = Field(default_factory=list, description="Categorization tags")

    @classmethod
    def default_for_type(cls, prompt_type: PromptType) -> "PromptMeta":
        """Get default metadata for a prompt type."""
        defaults: dict[PromptType, dict[str, Any]] = {
            PromptType.SOUL: {"priority": 100, "mutable": True},
            PromptType.MEMORY: {"priority": 90, "mutable": True},
            PromptType.SKILLS: {"priority": 80, "mutable": True},
            PromptType.USER: {"priority": 70, "mutable": True},
            PromptType.CONFIG: {"priority": 60, "mutable": True},
            PromptType.TASK: {"priority": 50, "mutable": False},
        }
        config = defaults.get(prompt_type, {})
        return cls(type=prompt_type, **config)


def _with_prompt_type(meta: PromptMeta, prompt_type: PromptType) -> PromptMeta:
    """Return a copy of metadata with an overridden prompt type."""
    return PromptMeta(**{**meta.model_dump(), "type": prompt_type})


class PromptDocument(BaseModel):
    """A complete parsed prompt document.

    Combines metadata from frontmatter with the prompt content body.
    """

    meta: PromptMeta = Field(description="Parsed frontmatter metadata")
    content: str = Field(description="Prompt body content (markdown)")
    source: Path | None = Field(default=None, description="Source file path")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_file(cls, path: Path) -> "PromptDocument":
        """Parse a prompt file with optional YAML frontmatter.

        Handles files with or without frontmatter gracefully.

        Args:
            path: Path to the prompt file

        Returns:
            Parsed PromptDocument

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")

        raw_content = path.read_text(encoding="utf-8")
        meta, content = _parse_frontmatter(raw_content)

        # Infer type from filename if not specified
        if meta.type == PromptType.SOUL:  # Default value
            inferred = _infer_type_from_filename(path.name)
            if inferred:
                meta = _with_prompt_type(meta, inferred)

        return cls(meta=meta, content=content, source=path)

    @classmethod
    def from_string(
        cls, content: str, prompt_type: PromptType = PromptType.TASK
    ) -> "PromptDocument":
        """Parse a prompt from string content.

        Args:
            content: Raw prompt content (may include frontmatter)
            prompt_type: Default type if not specified in frontmatter

        Returns:
            Parsed PromptDocument
        """
        meta, body = _parse_frontmatter(content)

        # Apply default type if still at default
        if meta.type == PromptType.SOUL:
            meta = _with_prompt_type(meta, prompt_type)

        return cls(meta=meta, content=body)

    def __bool__(self) -> bool:
        """Check if document has non-empty content."""
        return bool(self.content.strip())


def _parse_frontmatter(content: str) -> tuple[PromptMeta, str]:
    """Parse YAML frontmatter from content.

    Frontmatter format:
    ---
    key: value
    ---
    Content here...

    Args:
        content: Raw file content

    Returns:
        Tuple of (PromptMeta, body content)
    """
    content = content.strip()

    # Check for frontmatter delimiter
    if not content.startswith("---"):
        return PromptMeta(), content

    # Find closing delimiter
    lines = content.split("\n")
    end_index = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index is None:
        # No closing delimiter, treat as content
        return PromptMeta(), content

    # Extract and parse YAML
    yaml_content = "\n".join(lines[1:end_index])
    body = "\n".join(lines[end_index + 1 :]).strip()

    try:
        parsed = yaml.safe_load(yaml_content) or {}
        meta = PromptMeta(**parsed)
    except Exception as exc:
        logger.warning("Failed to parse frontmatter: %s", exc)
        meta = PromptMeta()

    return meta, body


def _infer_type_from_filename(filename: str) -> PromptType | None:
    """Infer prompt type from filename."""
    name_lower = filename.lower()

    mappings = {
        "soul": PromptType.SOUL,
        "memory": PromptType.MEMORY,
        "skills": PromptType.SKILLS,
        "user": PromptType.USER,
        "config": PromptType.CONFIG,
    }

    for key, prompt_type in mappings.items():
        if key in name_lower:
            return prompt_type

    # Files in tasks/ directory are task type
    return None
