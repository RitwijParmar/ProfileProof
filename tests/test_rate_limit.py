import pytest

from profileproof import rate_limit
from profileproof.rate_limit import SlidingWindowLimiter


@pytest.mark.asyncio
async def test_limiter_evicts_oldest_client_when_capacity_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now)
    limiter = SlidingWindowLimiter(requests=1, window_seconds=60, max_clients=2)

    assert (await limiter.allow("oldest"))[0] is True
    now = 101.0
    assert (await limiter.allow("newer"))[0] is True
    now = 102.0
    assert (await limiter.allow("new-client"))[0] is True
    assert (await limiter.allow("newer"))[0] is False
    assert (await limiter.allow("oldest"))[0] is True


@pytest.mark.asyncio
async def test_limiter_removes_expired_clients_before_evicting_active_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: now)
    limiter = SlidingWindowLimiter(requests=1, window_seconds=10, max_clients=2)

    assert (await limiter.allow("expired"))[0] is True
    now = 109.0
    assert (await limiter.allow("active"))[0] is True
    now = 111.0
    assert (await limiter.allow("replacement"))[0] is True
    assert (await limiter.allow("active"))[0] is False
