"""Behavioural tests for the Clock seam (T-020)."""

from datetime import UTC, datetime, timedelta

from harness.core.clock import Clock, FrozenClock, SystemClock


def test_system_clock_returns_aware_datetime_close_to_now() -> None:
    clock: Clock = SystemClock()
    before = datetime.now(UTC)
    observed = clock.now()
    after = datetime.now(UTC)
    assert observed.tzinfo is not None
    assert before <= observed <= after


def test_frozen_clock_returns_fixed_time_until_advanced() -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock: Clock = FrozenClock(fixed)
    assert clock.now() == fixed
    assert clock.now() == fixed  # repeated calls do not drift


def test_frozen_clock_advances_predictably() -> None:
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FrozenClock(fixed)
    clock.advance(timedelta(hours=2))
    assert clock.now() == fixed + timedelta(hours=2)
    clock.advance(timedelta(minutes=30))
    assert clock.now() == fixed + timedelta(hours=2, minutes=30)
