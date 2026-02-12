"""Base provider abstraction for LLM clients."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class Message:
    """Standardized message format for all providers."""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary format."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        """Create message from dictionary, ignoring extra fields."""
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
        )


class LLMProviderError(RuntimeError):
    """Base exception for LLM provider errors."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        payload: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.payload = payload


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str | None = None, **kwargs):
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'anthropic', 'ollama')."""
        pass

    @abstractmethod
    async def _create_client(self) -> httpx.AsyncClient:
        """Create and configure the HTTP client."""
        pass

    async def __aenter__(self) -> "BaseLLMProvider":
        """Async context manager entry."""
        self._client = await self._create_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        """Async context manager exit."""
        if self._client:
            await self._client.aclose()

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        *,
        model: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Send a non-streaming chat request."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        *,
        model: str,
        **kwargs,
    ) -> AsyncIterator[dict[str, Any]]:
        """Send a streaming chat request."""
        pass

    async def _handle_streaming_error(self, response: httpx.Response) -> None:
        """
        Handle errors for streaming responses.

        This centralizes the logic for reading error responses from streaming requests,
        which requires special handling in httpx.
        """
        provider_name = self.provider_name
        logger.info("[%s] Checking response status=%s", provider_name, response.status_code)
        try:
            response.raise_for_status()
            logger.info("[%s] Status check OK", provider_name)
        except httpx.HTTPStatusError as exc:
            logger.error("[%s] HTTP error detected: %s", provider_name, exc)
            payload: Any | None = None
            try:
                # For streaming responses, we must read the content first
                logger.info("[%s] Reading streaming response body...", provider_name)
                await response.aread()
                logger.info("[%s] Response body read successfully", provider_name)
                payload = response.json()
                logger.info("[%s] Parsed JSON payload", provider_name)
            except Exception as parse_exc:
                logger.error("[%s] Failed to parse JSON: %s", provider_name, parse_exc)
                try:
                    payload = response.text
                    logger.info("[%s] Got text payload", provider_name)
                except Exception as text_exc:
                    logger.error("[%s] Failed to get text: %s", provider_name, text_exc)
                    payload = None

            logger.error("[%s] Raising LLMProviderError with payload: %s", provider_name, payload)
            raise LLMProviderError(
                f"{provider_name.title()} API error ({response.status_code}).",
                provider=provider_name,
                status_code=response.status_code,
                payload=payload,
            ) from exc

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle non-streaming response errors."""
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            payload: Any | None = None
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            logger.error("[%s] API error payload: %s", self.provider_name, payload)
            raise LLMProviderError(
                f"{self.provider_name.title()} API error ({response.status_code}).",
                provider=self.provider_name,
                status_code=response.status_code,
                payload=payload,
            ) from exc
        return response.json()
