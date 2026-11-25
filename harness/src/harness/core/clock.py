"""Injected determinism seam for time. Real code uses `SystemClock`; tests use
`FrozenClock` so behaviour is reproducible (guidelines §3 — determinism is
injected, never assumed)."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that can report the current time."""

    def now(self) -> datetime: ...


class SystemClock:
    """Real clock backed by the system time, timezone-aware (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock that holds a fixed time until explicitly advanced."""

    def __init__(self, fixed: datetime) -> None:
        self._current = fixed

    def now(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current = self._current + delta
