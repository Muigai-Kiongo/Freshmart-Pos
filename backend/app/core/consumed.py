from __future__ import annotations

from datetime import datetime

from redis.asyncio import Redis

from app.core.clock import Clock, SystemClock


class ConsumedTokenStore:
    """Redis TTL store for single-use signup/reset JWT jti values."""

    def __init__(
        self, redis: Redis, clock: Clock | None = None, *, prefix: str = "consumed"
    ) -> None:
        self.redis = redis
        self.clock = clock or SystemClock()
        self.prefix = prefix

    def _key(self, purpose: str, jti: str) -> str:
        return f"{self.prefix}:{purpose}:{jti}"

    async def consume(self, *, purpose: str, jti: str, expires_at: datetime) -> bool:
        """Return True if this jti was freshly consumed, False if already used."""
        ttl = int(expires_at.timestamp() - self.clock.now().timestamp())
        if ttl <= 0:
            return False
        created = await self.redis.set(self._key(purpose, jti), "1", ex=ttl, nx=True)
        return bool(created)

    async def is_consumed(self, *, purpose: str, jti: str) -> bool:
        return bool(await self.redis.exists(self._key(purpose, jti)))
