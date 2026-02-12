"""Simple in-memory TTL cache."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    expires_at: float


class TTLCache:
    """Thread-safe TTL cache for small datasets."""

    def __init__(self, ttl_s: float) -> None:
        self._ttl_s = max(ttl_s, 0.0)
        self._items: dict[str, CacheEntry] = {}
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        now = monotonic()
        with self._lock:
            entry = self._items.get(key)
            if not entry:
                return None
            if entry.expires_at <= now:
                self._items.pop(key, None)
                return None
            return entry.value

    def set(self, key: str, value: Any) -> None:
        expires_at = monotonic() + self._ttl_s
        with self._lock:
            self._items[key] = CacheEntry(value=value, expires_at=expires_at)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
