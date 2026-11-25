"""Behavioural tests for interactive gates (T-150)."""

import pytest

from harness.core.errors import GateRejected
from harness.gates import GateResponse, apply_gate, phase_boundary_should_stop


def test_approve_proceeds_with_the_original_artifact() -> None:
    result = apply_gate(
        "artifact-v1", policy="interactive", io=lambda artifact: GateResponse(decision="approve")
    )
    assert result == "artifact-v1"


def test_edit_then_approve_proceeds_with_the_edited_artifact() -> None:
    result = apply_gate(
        "artifact-v1",
        policy="interactive",
        io=lambda artifact: GateResponse(decision="edit", edited_artifact="artifact-v2"),
    )
    assert result == "artifact-v2"


def test_reject_raises_gate_rejected_with_feedback() -> None:
    with pytest.raises(GateRejected, match="needs more detail"):
        apply_gate(
            "artifact-v1",
            policy="interactive",
            io=lambda artifact: GateResponse(decision="reject", feedback="needs more detail"),
        )


def test_auto_approve_proceeds_without_calling_io() -> None:
    calls: list[str] = []

    def io(artifact: str) -> GateResponse:
        calls.append(artifact)
        return GateResponse(decision="reject", feedback="should never be reached")

    result = apply_gate("artifact-v1", policy="auto_approve", io=io)
    assert result == "artifact-v1"
    assert calls == []


def test_phase_boundary_stop_policy_halts() -> None:
    assert phase_boundary_should_stop("stop") is True


def test_io_is_injected_so_no_real_terminal_is_needed() -> None:
    # the whole point of injected IO: a plain lambda stands in for a TTY.
    result = apply_gate(
        "x", policy="interactive", io=lambda artifact: GateResponse(decision="approve")
    )
    assert result == "x"
