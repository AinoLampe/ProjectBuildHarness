"""The single interface every stage implements (concept §5, guidelines §3).

A stage's own minimal surface is `inputs`, `outputs`, and `run()`; model/agent
resolution, prompt rendering, gating, recording, and budgeting are explicitly
the orchestrator's job, applied *around* the stage, never inside it. This is
what makes the pipeline replayable, resumable, and pure over the folder.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from harness.folder import DeclaredIOGuard, ProjectFolder


@dataclass(frozen=True)
class StageResult:
    """The outputs a stage actually wrote, plus any *new* blocking questions
    it discovered (so Stage 1a's self-review can re-enter its loop)."""

    outputs_written: list[Path]
    blocking_questions: list[str] = field(default_factory=list[str])


class Stage(Protocol):
    """`inputs`/`outputs` declare the exact files this stage may touch;
    `run()` produces the declared outputs from the declared inputs. Declared
    as read-only properties so both plain attributes and `@property`
    implementations satisfy the protocol structurally."""

    @property
    def inputs(self) -> list[Path]: ...

    @property
    def outputs(self) -> list[Path]: ...

    def run(self, folder: ProjectFolder, adapter: Any, rendered_prompt: str) -> StageResult: ...


def declared_io_for(stage: Stage, folder: ProjectFolder) -> DeclaredIOGuard:
    """The declared-IO guard (T-040) scoped to `stage`'s own declared
    inputs/outputs — wiring a stage into the single rule that it may only
    read its declared inputs and write its declared outputs."""
    return folder.declared_io(inputs=stage.inputs, outputs=stage.outputs)
