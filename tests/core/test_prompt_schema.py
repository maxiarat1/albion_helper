"""Tests for prompt schema definitions."""

import pytest
from pathlib import Path
from textwrap import dedent

from app.core.schema import (
    PromptMeta,
    PromptDocument,
    PromptType,
)
from app.core.schema.prompt_schema import (
    OutputContract,
    _parse_frontmatter,
    _infer_type_from_filename,
)


class TestPromptType:
    """Tests for PromptType enum."""

    def test_values(self):
        assert PromptType.SOUL == "soul"
        assert PromptType.TASK == "task"
        assert PromptType.MEMORY == "memory"
        assert PromptType.CONFIG == "config"
        assert PromptType.SKILLS == "skills"
        assert PromptType.USER == "user"


class TestOutputContract:
    """Tests for OutputContract enum."""

    def test_values(self):
        assert OutputContract.TEXT == "text"
        assert OutputContract.DATA == "data"
        assert OutputContract.ACTION == "action"
        assert OutputContract.ANY == "any"


class TestPromptMeta:
    """Tests for PromptMeta model."""

    def test_defaults(self):
        meta = PromptMeta()
        assert meta.version == "1.0"
        assert meta.type == PromptType.SOUL
        assert meta.mutable is True
        assert meta.priority == 50
        assert meta.output_contract == OutputContract.ANY
        assert meta.tags == []

    def test_from_dict(self):
        meta = PromptMeta(
            type="task",
            mutable=False,
            priority=30,
            output_contract="data",
            tags=["market", "prices"],
        )
        assert meta.type == PromptType.TASK
        assert meta.mutable is False
        assert meta.priority == 30
        assert meta.output_contract == OutputContract.DATA
        assert meta.tags == ["market", "prices"]

    def test_default_for_type(self):
        soul_meta = PromptMeta.default_for_type(PromptType.SOUL)
        assert soul_meta.priority == 100
        assert soul_meta.mutable is True

        task_meta = PromptMeta.default_for_type(PromptType.TASK)
        assert task_meta.priority == 50
        assert task_meta.mutable is False


class TestParseFrontmatter:
    """Tests for _parse_frontmatter function."""

    def test_no_frontmatter(self):
        content = "# Just a heading\n\nSome content."
        meta, body = _parse_frontmatter(content)
        assert meta == PromptMeta()
        assert body == content

    def test_with_frontmatter(self):
        content = dedent("""
        ---
        version: "2.0"
        type: task
        priority: 75
        ---
        # Task Content
        
        Do something useful.
        """).strip()

        meta, body = _parse_frontmatter(content)
        assert meta.version == "2.0"
        assert meta.type == PromptType.TASK
        assert meta.priority == 75
        assert body.startswith("# Task Content")

    def test_frontmatter_with_tags(self):
        content = dedent("""
        ---
        type: memory
        tags:
          - user
          - preferences
        ---
        Content here.
        """).strip()

        meta, body = _parse_frontmatter(content)
        assert meta.tags == ["user", "preferences"]

    def test_unclosed_frontmatter(self):
        """If frontmatter has no closing ---, treat whole thing as content."""
        content = "---\ntype: task\nThis is not frontmatter because no closing delimiter."
        meta, body = _parse_frontmatter(content)
        assert meta == PromptMeta()
        assert body == content

    def test_invalid_yaml(self, caplog):
        """Invalid YAML should log warning and use defaults."""
        import logging
        caplog.set_level(logging.WARNING)
        
        content = dedent("""
        ---
        type: [invalid yaml structure
        ---
        Content.
        """).strip()

        meta, body = _parse_frontmatter(content)
        assert "Failed to parse frontmatter" in caplog.text
        assert meta == PromptMeta()


class TestInferTypeFromFilename:
    """Tests for _infer_type_from_filename function."""

    def test_soul_detection(self):
        assert _infer_type_from_filename("SOUL.md") == PromptType.SOUL
        assert _infer_type_from_filename("my_soul.md") == PromptType.SOUL

    def test_memory_detection(self):
        assert _infer_type_from_filename("MEMORY.md") == PromptType.MEMORY

    def test_config_detection(self):
        assert _infer_type_from_filename("CONFIG.md") == PromptType.CONFIG

    def test_no_match(self):
        assert _infer_type_from_filename("random.md") is None
        assert _infer_type_from_filename("market_lookup.md") is None


class TestPromptDocument:
    """Tests for PromptDocument model."""

    def test_from_string_no_frontmatter(self):
        content = "# Simple Task\n\nDo the thing."
        doc = PromptDocument.from_string(content)
        assert doc.content == content
        assert doc.meta.type == PromptType.TASK  # Default for from_string

    def test_from_string_with_frontmatter(self):
        content = dedent("""
        ---
        type: memory
        priority: 85
        ---
        # Remembered Facts
        
        - User likes T4 gear
        """).strip()

        doc = PromptDocument.from_string(content)
        assert doc.meta.type == PromptType.MEMORY
        assert doc.meta.priority == 85
        assert "Remembered Facts" in doc.content

    def test_bool_empty_content(self):
        doc = PromptDocument(meta=PromptMeta(), content="")
        assert not doc

    def test_bool_whitespace_content(self):
        doc = PromptDocument(meta=PromptMeta(), content="   \n  ")
        assert not doc

    def test_bool_has_content(self):
        doc = PromptDocument(meta=PromptMeta(), content="Hello")
        assert doc

    def test_from_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            PromptDocument.from_file(tmp_path / "nonexistent.md")

    def test_from_file_success(self, tmp_path):
        file_path = tmp_path / "TEST_SOUL.md"
        file_path.write_text(dedent("""
        ---
        version: "1.5"
        priority: 99
        ---
        # Test Soul
        
        Be helpful.
        """).strip())

        doc = PromptDocument.from_file(file_path)
        assert doc.meta.version == "1.5"
        assert doc.meta.priority == 99
        assert doc.meta.type == PromptType.SOUL  # Inferred from filename
        assert doc.source == file_path
        assert "Test Soul" in doc.content


class TestPromptDocumentIntegration:
    """Integration tests with real-like prompt content."""

    def test_market_task_prompt(self):
        content = dedent("""
        ---
        version: "1.0"
        type: task
        mutable: false
        priority: 50
        output_contract: data
        response_schema: market_response
        tags:
          - market
          - prices
        ---
        # Task: Market Lookup
        
        ## Context
        The user is asking about market prices.
        
        ## Instructions
        1. Identify the item
        2. Fetch prices
        3. Present results
        """).strip()

        doc = PromptDocument.from_string(content, prompt_type=PromptType.TASK)
        
        assert doc.meta.type == PromptType.TASK
        assert doc.meta.mutable is False
        assert doc.meta.output_contract == OutputContract.DATA
        assert doc.meta.response_schema == "market_response"
        assert "market" in doc.meta.tags
        assert "Market Lookup" in doc.content
