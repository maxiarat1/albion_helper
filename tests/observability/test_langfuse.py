"""Tests for Langfuse observability integration."""

from __future__ import annotations

import sys
import types

from app.observability.langfuse import LangfuseConfig, LangfuseTracer


class _FakeGeneration:
    def __init__(self, updates: list[dict[str, object]]) -> None:
        self._updates = updates

    def __enter__(self) -> "_FakeGeneration":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def update(self, **kwargs) -> None:
        self._updates.append(kwargs)


class _FakeLangfuse:
    def __init__(self, **kwargs) -> None:
        self.init_kwargs = kwargs
        self.start_calls: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []
        self.flush_calls = 0

    def start_as_current_generation(self, **kwargs):
        self.start_calls.append(kwargs)
        return _FakeGeneration(self.updates)

    def flush(self) -> None:
        self.flush_calls += 1


def test_langfuse_tracer_noop_when_disabled():
    tracer = LangfuseTracer(
        LangfuseConfig(
            enabled=False,
            public_key=None,
            secret_key=None,
            base_url="https://cloud.langfuse.com",
            environment=None,
            release=None,
        )
    )
    assert tracer.enabled is False
    with tracer.start_generation(name="chat", model="x", prompt=[]) as generation:
        assert generation is None
    tracer.update_generation(None, output="ok")
    tracer.flush()


def test_langfuse_tracer_records_generation(monkeypatch):
    fake_module = types.ModuleType("langfuse")
    fake_module.Langfuse = _FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)

    tracer = LangfuseTracer(
        LangfuseConfig(
            enabled=True,
            public_key="pk",
            secret_key="sk",
            base_url="https://cloud.langfuse.com",
            environment="test",
            release="1.2.3",
        )
    )
    assert tracer.enabled is True

    with tracer.start_generation(
        name="chat.completion",
        model="gpt-test",
        prompt=[{"role": "user", "content": "hello"}],
        model_parameters={"temperature": 0.2, "api_key": "dont-log"},
        metadata={"session_id": "abc", "token": "secret"},
    ) as generation:
        tracer.update_generation(
            generation,
            output="hi",
            usage_details={"input": "10", "output": 4, "bad": "x"},
            metadata={"status": "ok"},
        )

    tracer.flush()

    client = tracer._client
    assert client is not None
    assert client.init_kwargs["public_key"] == "pk"
    assert client.init_kwargs["environment"] == "test"
    assert client.start_calls[0]["model_parameters"]["api_key"] == "[REDACTED]"
    assert client.start_calls[0]["metadata"]["token"] == "[REDACTED]"
    assert client.updates[0]["usage_details"] == {"input": 10, "output": 4}
    assert client.flush_calls == 1
