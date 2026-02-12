"""Gemini provider implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from ..base_provider import BaseLLMProvider, Message
from ..config import GeminiConfig

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """Gemini LLM provider."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
    ):
        super().__init__(api_key=api_key)
        config = GeminiConfig()
        self._api_key = api_key or config.api_key
        self._base_url = (base_url or config.base_url).rstrip("/")
        self._timeout_s = timeout_s or config.timeout_s
        if self._base_url.endswith("/v1") or self._base_url.endswith("/v1beta"):
            self._api_prefix = ""
        else:
            self._api_prefix = "/v1beta"

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client for Gemini."""
        if not self._api_key:
            raise ValueError("Gemini API key is required")
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
        )

    def _format_model(self, model: str) -> str:
        """Ensure model name is in API format."""
        if model.startswith(("models/", "tunedModels/")):
            return model
        return f"models/{model}"

    def _endpoint(self, model: str, action: str) -> str:
        """Build API endpoint path."""
        if not action.startswith(":"):
            action = f":{action}"
        model_path = self._format_model(model)
        path = f"/{model_path}{action}"
        if self._api_prefix:
            path = f"{self._api_prefix}{path}"
        return path

    def _messages_to_gemini_format(
        self,
        messages: list[Message],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Convert Message objects to Gemini API format."""
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append({"text": msg.content})
                continue

            role = "model" if msg.role == "assistant" else "user"
            contents.append(
                {
                    "role": role,
                    "parts": [{"text": msg.content}],
                }
            )

        system_instruction = {"parts": system_parts} if system_parts else None
        if not contents and system_instruction:
            contents.append({"role": "user", "parts": system_parts})
            system_instruction = None

        return contents, system_instruction

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

        contents, system_instruction = self._messages_to_gemini_format(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
        payload.update(kwargs)

        response = await self._client.post(self._endpoint(model, "generateContent"), json=payload)
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

        contents, system_instruction = self._messages_to_gemini_format(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = system_instruction
        payload.update(kwargs)

        provider_name = self.provider_name
        logger.info("[%s] Starting stream_chat with model=%s", provider_name, model)
        async with self._client.stream(
            "POST",
            self._endpoint(model, "streamGenerateContent"),
            params={"alt": "sse"},
            json=payload,
        ) as response:
            logger.info("[%s] Got streaming response, status=%s", provider_name, response.status_code)
            await self._handle_streaming_error(response)
            logger.info("[%s] Status check passed, iterating lines", provider_name)

            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    data = line.split("data:", 1)[1].strip()
                    if not data or data == "[DONE]":
                        continue
                    yield json.loads(data)
                    continue
                if line.startswith("{"):
                    yield json.loads(line)
