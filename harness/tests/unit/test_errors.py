"""Behavioural tests for the typed exception hierarchy (T-020)."""

import pytest

from harness.core.errors import (
    AdapterError,
    BudgetExceeded,
    ConfigError,
    DagCycleError,
    FolderError,
    GateRejected,
    HarnessError,
    SandboxError,
    StageError,
)

ALL_SUBCLASSES = [
    ConfigError,
    FolderError,
    StageError,
    BudgetExceeded,
    GateRejected,
    SandboxError,
    AdapterError,
    DagCycleError,
]


@pytest.mark.parametrize("exc_type", ALL_SUBCLASSES)
def test_every_subclass_is_a_harness_error(exc_type: type[HarnessError]) -> None:
    assert issubclass(exc_type, HarnessError)


def test_subclasses_are_catchable_as_harness_error() -> None:
    with pytest.raises(HarnessError):
        raise ConfigError("bad field")


def test_harness_error_carries_message() -> None:
    err = StageError("stage failed")
    assert str(err) == "stage failed"
