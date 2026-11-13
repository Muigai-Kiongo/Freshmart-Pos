from __future__ import annotations

from datetime import timedelta

from app.core.consumed import ConsumedTokenStore


async def test_consume_is_single_use(redis, clock) -> None:
    store = ConsumedTokenStore(redis, clock)
    expires = clock.now() + timedelta(minutes=15)
    assert await store.consume(purpose="signup", jti="abc", expires_at=expires)
    assert not await store.consume(purpose="signup", jti="abc", expires_at=expires)
    assert await store.is_consumed(purpose="signup", jti="abc")
    assert not await store.is_consumed(purpose="signup", jti="other")


async def test_expired_jti_not_stored(redis, clock) -> None:
    store = ConsumedTokenStore(redis, clock)
    expires = clock.now() - timedelta(seconds=1)
    assert not await store.consume(purpose="reset", jti="late", expires_at=expires)
