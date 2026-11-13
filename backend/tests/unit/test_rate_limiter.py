from __future__ import annotations

from app.core.rate_limit import SlidingWindowRateLimiter


async def test_sliding_window_blocks_then_allows(redis, clock) -> None:
    limiter = SlidingWindowRateLimiter(redis, clock)
    for _ in range(3):
        result = await limiter.hit("ip:1.1.1.1:signup", limit=3, window_seconds=3600)
        assert result.allowed
    blocked = await limiter.hit("ip:1.1.1.1:signup", limit=3, window_seconds=3600)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 3600

    clock.advance(seconds=3601)
    allowed = await limiter.hit("ip:1.1.1.1:signup", limit=3, window_seconds=3600)
    assert allowed.allowed


async def test_independent_keys(redis, clock) -> None:
    limiter = SlidingWindowRateLimiter(redis, clock)
    await limiter.hit("phone:254712345678", limit=1, window_seconds=60)
    other = await limiter.hit("phone:254798765432", limit=1, window_seconds=60)
    assert other.allowed
