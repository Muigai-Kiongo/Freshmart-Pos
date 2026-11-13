from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.clock import Clock, SystemClock


@dataclass(frozen=True)
class LockoutStatus:
    locked: bool
    failures: int
    streak: int
    retry_after_seconds: int


class AccountLockout:
    """
    5 failures -> lockout. Base duration 15 minutes, doubled on each repeat
    lockout until a successful login resets the streak.
    """

    def __init__(
        self,
        redis: Redis,
        clock: Clock | None = None,
        *,
        prefix: str = "lockout",
        max_failures: int = 5,
        base_seconds: int = 15 * 60,
        max_seconds: int = 12 * 60 * 60,
    ) -> None:
        self.redis = redis
        self.clock = clock or SystemClock()
        self.prefix = prefix
        self.max_failures = max_failures
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds

    def _fail_key(self, name: str) -> str:
        return f"{self.prefix}:fail:{name}"

    def _locked_key(self, name: str) -> str:
        return f"{self.prefix}:locked:{name}"

    def _streak_key(self, name: str) -> str:
        return f"{self.prefix}:streak:{name}"

    def _now(self) -> float:
        return self.clock.now().timestamp()

    async def status(self, name: str) -> LockoutStatus:
        locked_until = await self.redis.get(self._locked_key(name))
        failures = int(await self.redis.get(self._fail_key(name)) or 0)
        streak = int(await self.redis.get(self._streak_key(name)) or 0)
        if locked_until is None:
            return LockoutStatus(
                locked=False, failures=failures, streak=streak, retry_after_seconds=0
            )
        until = float(locked_until)
        remaining = max(int(until - self._now()), 0)
        if remaining <= 0:
            await self.redis.delete(self._locked_key(name))
            return LockoutStatus(
                locked=False, failures=failures, streak=streak, retry_after_seconds=0
            )
        return LockoutStatus(
            locked=True, failures=failures, streak=streak, retry_after_seconds=remaining
        )

    async def register_failure(self, name: str) -> LockoutStatus:
        current = await self.status(name)
        if current.locked:
            return current
        failures = await self.redis.incr(self._fail_key(name))
        await self.redis.expire(self._fail_key(name), self.max_seconds)
        if failures < self.max_failures:
            streak = int(await self.redis.get(self._streak_key(name)) or 0)
            return LockoutStatus(
                locked=False,
                failures=int(failures),
                streak=streak,
                retry_after_seconds=0,
            )

        streak = await self.redis.incr(self._streak_key(name))
        await self.redis.expire(self._streak_key(name), self.max_seconds)
        duration = min(self.base_seconds * (2 ** (int(streak) - 1)), self.max_seconds)
        until = self._now() + duration
        await self.redis.set(self._locked_key(name), str(until), ex=duration)
        await self.redis.delete(self._fail_key(name))
        return LockoutStatus(
            locked=True,
            failures=self.max_failures,
            streak=int(streak),
            retry_after_seconds=duration,
        )

    async def register_success(self, name: str) -> None:
        await self.redis.delete(
            self._fail_key(name), self._locked_key(name), self._streak_key(name)
        )
