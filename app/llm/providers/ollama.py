"""Ollama provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from ..base_provider import BaseLLMProvider, Message
from ..config import OllamaConfig

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """Ollama LLM provider."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(api_key=None)  # Ollama doesn't use API keys
        config = OllamaConfig()
        self._base_url = (base_url or config.base_url).rstrip("/")
        self._timeout_s = timeout_s or config.timeout_s
        self._api_prefix = "" if self._base_url.endswith("/api") else "/api"

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client for Ollama."""
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers={"Accept": "application/json"},
        )

    def _endpoint(self, path: str) -> str:
        """Build API endpoint path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._api_prefix}{path}"

    def _messages_to_ollama_format(self, messages: list[Message]) -> list[dict[str, str]]:
        """Convert Message objects to Ollama API format."""
        return [msg.to_dict() for msg in messages]

    async def list_models(self) -> dict[str, Any]:
        """List available Ollama models."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        response = await self._client.get(self._endpoint("/tags"))
        return self._handle_response(response)

    async def show_model(self, model: str) -> dict[str, Any]:
        """Fetch detailed metadata for a specific Ollama model."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")
        response = await self._client.post(self._endpoint("/show"), json={"model": model})
        return self._handle_response(response)

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Send non-streaming chat request."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages_to_ollama_format(messages),
            "stream": False,
        }
        payload.update(kwargs)

        response = await self._client.post(self._endpoint("/chat"), json=payload)
        return self._handle_response(response)

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        **kwargs,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send streaming chat request."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._messages_to_ollama_format(messages),
            "stream": True,
        }
        payload.update(kwargs)

        provider_name = self.provider_name
        logger.info("[%s] Starting stream_chat with model=%s", provider_name, model)
        async with self._client.stream("POST", self._endpoint("/chat"), json=payload) as response:
            logger.info("[%s] Got streaming response, status=%s", provider_name, response.status_code)
            await self._handle_streaming_error(response)
            logger.info("[%s] Status check passed, iterating lines", provider_name)

            async for line in response.aiter_lines():
                if not line:
                    continue
                yield json.loads(line)
