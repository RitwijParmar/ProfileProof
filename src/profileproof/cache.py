import asyncio
import time
from dataclasses import dataclass


@dataclass
class _Entry[T]:
    value: T
    expires_at: float


class TtlCache[T]:
    def __init__(self, ttl_seconds: int, max_entries: int = 512) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry[T]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                self._entries.pop(key, None)
                return None
            return entry.value

    async def put(self, key: str, value: T) -> None:
        if self._ttl == 0:
            return
        async with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda item: self._entries[item].expires_at)
                self._entries.pop(oldest, None)
            self._entries[key] = _Entry(value, time.monotonic() + self._ttl)
