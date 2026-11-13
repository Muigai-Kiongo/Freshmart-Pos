from __future__ import annotations

from datetime import UTC, datetime

from app.core.clock import FakeClock, SystemClock, utcnow


def test_system_clock_returns_utc_aware_time() -> None:
    assert utcnow().tzinfo is UTC
    assert SystemClock().now().tzinfo is UTC


def test_fake_clock_defaults_to_now_and_accepts_naive_set_value() -> None:
    clock = FakeClock()
    assert clock.now().tzinfo is UTC

    clock.set(datetime(2026, 11, 9, 12, 0))
    assert clock.now() == datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def test_fake_clock_advance_returns_updated_time() -> None:
    initial = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    clock = FakeClock(initial)

    updated = clock.advance(minutes=2, seconds=3)

    assert updated == datetime(2026, 11, 9, 12, 2, 3, tzinfo=UTC)
    assert clock.now() == updated
