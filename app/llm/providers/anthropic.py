"""Anthropic provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from ..base_provider import BaseLLMProvider, Message
from ..config import AnthropicConfig

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseLLMProvider):
    """Anthropic (Claude) LLM provider."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        version: str | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(api_key=api_key)
        config = AnthropicConfig()
        self._api_key = api_key or config.api_key
        self._base_url = (base_url or config.base_url).rstrip("/")
        self._version = version or config.version
        self._timeout_s = timeout_s or config.timeout_s
        self._api_prefix = "" if self._base_url.endswith("/v1") else "/v1"

    @property
    def provider_name(self) -> str:
        return "anthropic"

    async def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client with Anthropic headers."""
        if not self._api_key:
            raise ValueError("Anthropic API key is required")
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers={
                "Accept": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": self._version,
            },
        )

    def _endpoint(self, path: str) -> str:
        """Build API endpoint path."""
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._api_prefix}{path}"

    def _messages_to_anthropic_format(
        self, messages: list[Message]
    ) -> tuple[list[dict[str, str]], str | None]:
        """Convert Message objects to Anthropic API format.

        Anthropic requires system messages to be passed separately via the
        `system` parameter, not in the messages array. This method extracts
        system messages and returns them separately.

        Returns:
            A tuple of (messages_list, system_prompt) where messages_list
            contains only user/assistant messages and system_prompt is the
            concatenated system content (or None if no system messages).
        """
        system_parts: list[str] = []
        chat_messages: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
            else:
                chat_messages.append(msg.to_dict())

        system_prompt = "\n\n".join(system_parts) if system_parts else None
        return chat_messages, system_prompt

    async def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int = 1024,
        **kwargs,
    ) -> dict[str, Any]:
        """Send non-streaming chat request."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        chat_messages, system_prompt = self._messages_to_anthropic_format(messages)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": chat_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload.update(kwargs)

        response = await self._client.post(self._endpoint("/messages"), json=payload)
        return self._handle_response(response)

    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int = 1024,
        **kwargs,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send streaming chat request."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        chat_messages, system_prompt = self._messages_to_anthropic_format(messages)

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": chat_messages,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload.update(kwargs)

        provider_name = self.provider_name
        logger.info("[%s] Starting stream_chat with model=%s", provider_name, model)
        async with self._client.stream("POST", self._endpoint("/messages"), json=payload) as response:
            logger.info("[%s] Got streaming response, status=%s", provider_name, response.status_code)
            await self._handle_streaming_error(response)
            logger.info("[%s] Status check passed, iterating lines", provider_name)

            event: str | None = None
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event = line.split("event:", 1)[1].strip()
                    continue
                if not line.startswith("data:"):
                    continue

                data = line.split("data:", 1)[1].strip()
                if not data:
                    continue

                payload = json.loads(data)
                yield {"event": event, "data": payload}
