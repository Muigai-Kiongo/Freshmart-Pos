from __future__ import annotations

from app.core.lockout import AccountLockout


async def test_locks_after_five_failures(redis, clock) -> None:
    lockout = AccountLockout(redis, clock, max_failures=5, base_seconds=15 * 60)
    for _ in range(4):
        status = await lockout.register_failure("staff:abc")
        assert not status.locked
    locked = await lockout.register_failure("staff:abc")
    assert locked.locked
    assert locked.retry_after_seconds == 15 * 60

    clock.advance(minutes=14)
    still = await lockout.status("staff:abc")
    assert still.locked

    clock.advance(minutes=2)
    opened = await lockout.status("staff:abc")
    assert not opened.locked


async def test_escalates_on_repeat_lockout(redis, clock) -> None:
    lockout = AccountLockout(redis, clock, max_failures=5, base_seconds=15 * 60)
    for _ in range(5):
        await lockout.register_failure("staff:abc")
    clock.advance(minutes=16)
    for _ in range(5):
        second = await lockout.register_failure("staff:abc")
    assert second.locked
    assert second.retry_after_seconds == 30 * 60


async def test_success_clears_lockout(redis, clock) -> None:
    lockout = AccountLockout(redis, clock, max_failures=5, base_seconds=15 * 60)
    for _ in range(5):
        await lockout.register_failure("staff:abc")
    await lockout.register_success("staff:abc")
    status = await lockout.status("staff:abc")
    assert not status.locked
    assert status.failures == 0
    assert status.streak == 0
