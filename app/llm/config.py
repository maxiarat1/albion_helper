"""LLM configuration settings."""

from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model: str | None = os.getenv("OLLAMA_MODEL") or None
    timeout_s: float = float(os.getenv("OLLAMA_TIMEOUT_S", "30"))


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
    model: str | None = os.getenv("OPENAI_MODEL") or None
    timeout_s: float = float(os.getenv("OPENAI_TIMEOUT_S", "30"))


@dataclass(frozen=True)
class AnthropicConfig:
    api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    base_url: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    model: str | None = os.getenv("ANTHROPIC_MODEL") or None
    version: str = os.getenv("ANTHROPIC_VERSION", "2023-06-01")
    timeout_s: float = float(os.getenv("ANTHROPIC_TIMEOUT_S", "30"))


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    base_url: str = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
    model: str | None = os.getenv("GEMINI_MODEL") or None
    timeout_s: float = float(os.getenv("GEMINI_TIMEOUT_S", "30"))
