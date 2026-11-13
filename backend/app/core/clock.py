from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


def utcnow() -> datetime:
    return datetime.now(UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class FakeClock:
    """Injectable clock for tests (rate limits, lockouts, JWT expiry)."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or utcnow()
        if self._now.tzinfo is None:
            self._now = self._now.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        self._now = when

    def advance(self, **delta: float) -> datetime:
        self._now = self._now + timedelta(**delta)
        return self._now
