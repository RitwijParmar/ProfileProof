import asyncio
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, requests: int, window_seconds: int, max_clients: int = 10_000) -> None:
        self._limit = requests
        self._window = window_seconds
        self._max_clients = max_clients
        self._clients: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, client: str) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - self._window
        async with self._lock:
            if client not in self._clients and len(self._clients) >= self._max_clients:
                expired = [
                    key
                    for key, values in self._clients.items()
                    if not values or values[-1] <= cutoff
                ]
                for key in expired:
                    self._clients.pop(key, None)
                if len(self._clients) >= self._max_clients:
                    oldest = min(
                        self._clients,
                        key=lambda key: self._clients[key][-1],
                    )
                    self._clients.pop(oldest, None)
            timestamps = self._clients.setdefault(client, deque())
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._limit:
                retry_after = max(1, int(self._window - (now - timestamps[0])))
                return False, 0, retry_after
            timestamps.append(now)
            return True, self._limit - len(timestamps), 0
