"""Provider factory for creating LLM providers."""

from __future__ import annotations

from typing import Any

from .base_provider import BaseLLMProvider
from .providers.anthropic import AnthropicProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider


class ProviderFactory:
    """Factory for creating LLM provider instances."""

    @staticmethod
    def create(provider_name: str, api_key: str | None = None, **kwargs) -> BaseLLMProvider:
        """
        Create a provider instance by name.

        Args:
            provider_name: Name of the provider (ollama, anthropic, openai, gemini)
            api_key: Optional API key for the provider
            **kwargs: Additional provider-specific arguments

        Returns:
            BaseLLMProvider instance

        Raises:
            ValueError: If provider name is unknown
        """
        provider_name = provider_name.lower()

        if provider_name == "ollama":
            return OllamaProvider(**kwargs)
        elif provider_name == "anthropic":
            return AnthropicProvider(api_key=api_key, **kwargs)
        elif provider_name == "openai":
            return OpenAIProvider(api_key=api_key, **kwargs)
        elif provider_name == "gemini":
            return GeminiProvider(api_key=api_key, **kwargs)
        else:
            raise ValueError(f"Unknown provider: {provider_name}")

    @staticmethod
    def get_supported_providers() -> list[str]:
        """Get list of supported provider names."""
        return ["ollama", "anthropic", "openai", "gemini"]
