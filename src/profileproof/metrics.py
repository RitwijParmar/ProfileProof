import asyncio
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._provider_calls: Counter[tuple[str, str]] = Counter()
        self._lock = asyncio.Lock()

    async def record_request(self, method: str, route: str, status: int) -> None:
        async with self._lock:
            self._requests[(method, route, status)] += 1

    async def record_provider(self, provider: str, outcome: str) -> None:
        async with self._lock:
            self._provider_calls[(provider, outcome)] += 1

    async def render(self) -> str:
        async with self._lock:
            lines = [
                "# HELP profileproof_http_requests_total HTTP requests.",
                "# TYPE profileproof_http_requests_total counter",
            ]
            for (method, route, status), count in sorted(self._requests.items()):
                lines.append(
                    "profileproof_http_requests_total"
                    f'{{method="{method}",route="{route}",status="{status}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP profileproof_provider_calls_total Provider calls.",
                    "# TYPE profileproof_provider_calls_total counter",
                ]
            )
            for (provider, outcome), count in sorted(self._provider_calls.items()):
                lines.append(
                    "profileproof_provider_calls_total"
                    f'{{provider="{provider}",outcome="{outcome}"}} {count}'
                )
            return "\n".join(lines) + "\n"
