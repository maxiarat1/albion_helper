"""LLM module with provider abstraction."""

from .base_provider import BaseLLMProvider, LLMProviderError, Message
from .config import AnthropicConfig, GeminiConfig, OllamaConfig, OpenAIConfig
from .provider_factory import ProviderFactory
from .providers.anthropic import AnthropicProvider
from .providers.gemini import GeminiProvider
from .providers.ollama import OllamaProvider
from .providers.openai import OpenAIProvider

__all__ = [
    # Base classes
    "BaseLLMProvider",
    "LLMProviderError",
    "Message",
    # Factory
    "ProviderFactory",
    # Providers
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    # Configs
    "AnthropicConfig",
    "GeminiConfig",
    "OllamaConfig",
    "OpenAIConfig",
]
