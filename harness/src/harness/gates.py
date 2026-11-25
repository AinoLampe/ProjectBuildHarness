"""Human-in-the-loop gates (concept §11): approve / edit-then-approve /
reject, honouring per-stage policy. IO is injected so gates are fully
testable without a real terminal."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from harness.core.errors import GateRejected

GateDecision = Literal["approve", "edit", "reject"]
GatePolicy = Literal["interactive", "auto_approve"]


@dataclass(frozen=True)
class GateResponse:
    decision: GateDecision
    edited_artifact: str | None = None
    feedback: str | None = None


GateIO = Callable[[str], GateResponse]


def apply_gate(artifact: str, *, policy: GatePolicy, io: GateIO) -> str:
    """Apply the gate policy to `artifact`, returning the artifact to
    proceed with (the original, or the edited version). `auto_approve`
    proceeds without consulting `io` at all. A `reject` response raises
    `GateRejected` carrying the feedback."""
    if policy == "auto_approve":
        return artifact

    response = io(artifact)

    if response.decision == "approve":
        return artifact
    if response.decision == "edit":
        return response.edited_artifact if response.edited_artifact is not None else artifact

    raise GateRejected(response.feedback or "gate rejected with no feedback given")


def phase_boundary_should_stop(policy: Literal["stop"]) -> bool:
    """`phase_boundary: stop` halts the pipeline after the active phase,
    awaiting a go-ahead (concept §6.3, §11)."""
    return policy == "stop"
