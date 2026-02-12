"""Langfuse integration with safe no-op fallback."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "secret",
    "secret_key",
    "password",
}
_SAFE_TOKEN_KEY_SUFFIXES = {
    "max_tokens",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            is_sensitive = lowered in _SENSITIVE_KEYS
            if lowered.endswith("_token") and lowered not in _SAFE_TOKEN_KEY_SUFFIXES:
                is_sensitive = True
            if is_sensitive:
                sanitized[key_text] = "[REDACTED]"
                continue
            sanitized[key_text] = _sanitize_mapping(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_mapping(item) for item in value)
    return value


def _safe_usage_details(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    usage: dict[str, int] = {}
    for key, value in raw.items():
        try:
            usage[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return usage or None


@dataclass(frozen=True)
class LangfuseConfig:
    """Runtime config sourced from environment variables."""

    enabled: bool
    public_key: str | None
    secret_key: str | None
    base_url: str
    environment: str | None
    release: str | None

    @classmethod
    def from_env(cls) -> "LangfuseConfig":
        public_key = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip() or None
        secret_key = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip() or None
        default_enabled = bool(public_key and secret_key)
        enabled = _env_bool("LANGFUSE_ENABLED", default_enabled)
        base_url = (os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com").strip()
        environment = (
            (os.getenv("LANGFUSE_TRACING_ENVIRONMENT") or "").strip()
            or (os.getenv("LANGFUSE_ENV") or "").strip()
            or None
        )
        release = (os.getenv("LANGFUSE_RELEASE") or "").strip() or None
        return cls(
            enabled=enabled,
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            environment=environment,
            release=release,
        )


class LangfuseTracer:
    """Thin wrapper around Langfuse SDK with graceful fallback."""

    def __init__(self, config: LangfuseConfig | None = None) -> None:
        self._config = config or LangfuseConfig.from_env()
        self._client: Any | None = None
        self._initialize()

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def _initialize(self) -> None:
        if not self._config.enabled:
            return
        if not self._config.public_key or not self._config.secret_key:
            logger.warning(
                "Langfuse disabled: LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required."
            )
            return

        try:
            from langfuse import Langfuse  # type: ignore
        except Exception as exc:
            logger.warning("Langfuse SDK unavailable; tracing disabled: %s", exc)
            return

        kwargs: dict[str, Any] = {
            "public_key": self._config.public_key,
            "secret_key": self._config.secret_key,
            "base_url": self._config.base_url,
        }
        if self._config.environment:
            kwargs["environment"] = self._config.environment
        if self._config.release:
            kwargs["release"] = self._config.release

        try:
            self._client = Langfuse(**kwargs)
            logger.info("Langfuse tracing enabled.")
        except TypeError:
            # Compatibility for older SDK versions that used host=...
            compat_kwargs = dict(kwargs)
            compat_kwargs["host"] = compat_kwargs.pop("base_url")
            try:
                self._client = Langfuse(**compat_kwargs)
                logger.info("Langfuse tracing enabled.")
            except Exception as exc:
                logger.warning("Failed to initialize Langfuse client; tracing disabled: %s", exc)
                self._client = None
        except Exception as exc:
            logger.warning("Failed to initialize Langfuse client; tracing disabled: %s", exc)
            self._client = None

    def start_generation(
        self,
        *,
        name: str,
        model: str,
        prompt: Any,
        model_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[Any]:
        if not self._client:
            return nullcontext(None)

        sanitized_parameters = _sanitize_mapping(model_parameters or {})
        sanitized_metadata = _sanitize_mapping(metadata or {})
        sanitized_prompt = _sanitize_mapping(prompt)

        try:
            return self._client.start_as_current_generation(
                name=name,
                model=model,
                input=sanitized_prompt,
                model_parameters=sanitized_parameters,
                metadata=sanitized_metadata,
            )
        except Exception as exc:
            logger.warning("Langfuse start_generation failed; tracing skipped: %s", exc)
            return nullcontext(None)

    def update_generation(
        self,
        generation: Any,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        usage_details: dict[str, int] | None = None,
        status_message: str | None = None,
    ) -> None:
        if not generation:
            return
        payload: dict[str, Any] = {}
        if output is not None:
            payload["output"] = _sanitize_mapping(output)
        if metadata is not None:
            payload["metadata"] = _sanitize_mapping(metadata)
        usage = _safe_usage_details(usage_details)
        if usage:
            payload["usage_details"] = usage
        if status_message:
            payload["status_message"] = status_message
        if not payload:
            return

        try:
            generation.update(**payload)
        except Exception as exc:
            logger.warning("Langfuse generation update failed: %s", exc)

    def flush(self) -> None:
        if not self._client:
            return
        try:
            self._client.flush()
        except Exception as exc:
            logger.warning("Langfuse flush failed: %s", exc)
