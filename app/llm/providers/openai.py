"""OpenAI provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from ..base_provider import BaseLLMProvider, Message
from ..config import OpenAIConfig

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """OpenAI LLM provider."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(api_key=api_key)
        config = OpenAIConfig()
        self._api_key = api_key or config.api_key
        self._base_url = (base_url or config.base_url).rstrip("/")
        self._timeout_s = timeout_s or config.timeout_s
        self._api_prefix = "" if self._base_url.endswith("/v1") else "/v1"

    @property
    def provider_name(self) -> str:
        return "openai"

    async def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client for OpenAI."""
        if not self._api_key:
            raise ValueError("OpenAI API key is required")
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )

    def _endpoint(self, path: str) -> str:
        """Build API endpoint path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._api_prefix}{path}"

    def _messages_to_openai_format(self, messages: list[Message]) -> list[dict[str, str]]:
        """Convert Message objects to OpenAI API format."""
        return [msg.to_dict() for msg in messages]

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
            "messages": self._messages_to_openai_format(messages),
        }
        payload.update(kwargs)

        response = await self._client.post(self._endpoint("/chat/completions"), json=payload)
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
            "messages": self._messages_to_openai_format(messages),
            "stream": True,
        }
        payload.update(kwargs)

        provider_name = self.provider_name
        logger.info("[%s] Starting stream_chat with model=%s", provider_name, model)
        async with self._client.stream("POST", self._endpoint("/chat/completions"), json=payload) as response:
            logger.info("[%s] Got streaming response, status=%s", provider_name, response.status_code)
            await self._handle_streaming_error(response)
            logger.info("[%s] Status check passed, iterating lines", provider_name)

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line.split("data:", 1)[1].strip()
                if not data:
                    continue
                if data == "[DONE]":
                    break
                yield json.loads(data)
