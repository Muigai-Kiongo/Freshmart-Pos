from __future__ import annotations

import secrets
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.clock import Clock, SystemClock


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    count: int


class SlidingWindowRateLimiter:
    """Redis sorted-set sliding window. Key names must not include secrets."""

    def __init__(
        self, redis: Redis, clock: Clock | None = None, *, prefix: str = "rl"
    ) -> None:
        self.redis = redis
        self.clock = clock or SystemClock()
        self.prefix = prefix

    def _key(self, name: str) -> str:
        return f"{self.prefix}:{name}"

    def _now_ms(self) -> int:
        return int(self.clock.now().timestamp() * 1000)

    async def hit(
        self, name: str, *, limit: int, window_seconds: int
    ) -> RateLimitResult:
        key = self._key(name)
        now_ms = self._now_ms()
        window_ms = window_seconds * 1000
        oldest = now_ms - window_ms
        member = f"{now_ms}:{secrets.token_hex(8)}"
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(key, 0, oldest)
        pipe.zadd(key, {member: now_ms})
        pipe.zcard(key)
        pipe.pexpire(key, window_ms)
        results = await pipe.execute()
        count = int(results[2])
        remaining = max(limit - count, 0)
        allowed = count <= limit
        retry_after = 0 if allowed else window_seconds
        if not allowed:
            # Remove the overflowing hit so the window count stays at the limit.
            await self.redis.zrem(key, member)
            count = limit
            remaining = 0
        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            retry_after_seconds=retry_after,
            count=count,
        )
