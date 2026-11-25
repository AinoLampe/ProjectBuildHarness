"""Behavioural tests for the Stage contract (T-160)."""

from pathlib import Path
from typing import Any

import pytest

from harness.core.errors import FolderError
from harness.folder import ProjectFolder
from harness.stages.base import Stage, StageResult, declared_io_for


class _FakeStage:
    """A trivial stage: reads `requirements.md`, writes `spec/concept.md`."""

    def __init__(self, folder: ProjectFolder) -> None:
        self.inputs: list[Path] = [folder.requirements_md]
        self.outputs: list[Path] = [folder.spec_concept_md]

    def run(self, folder: ProjectFolder, adapter: Any, rendered_prompt: str) -> StageResult:
        guard = declared_io_for(self, folder)
        requirements = guard.read_text(folder.requirements_md)
        guard.write_text(folder.spec_concept_md, f"# Concept\n\n{requirements}\n{rendered_prompt}")
        return StageResult(outputs_written=[folder.spec_concept_md])


def test_trivial_fake_stage_conforms_to_the_protocol(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    stage: Stage = _FakeStage(folder)
    assert stage.inputs == [folder.requirements_md]
    assert stage.outputs == [folder.spec_concept_md]


def test_stage_run_produces_declared_outputs(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    stage = _FakeStage(folder)

    result = stage.run(folder, adapter=None, rendered_prompt="prompt text")

    assert result.outputs_written == [folder.spec_concept_md]
    assert "build a thing" in folder.spec_concept_md.read_text(encoding="utf-8")


def test_declared_io_guard_rejects_reading_an_undeclared_input(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "reqs")
    folder.write_text(folder.instructions_md, "extra instructions")
    stage = _FakeStage(folder)
    guard = declared_io_for(stage, folder)

    with pytest.raises(FolderError):
        guard.read_text(folder.instructions_md)


def test_declared_io_guard_rejects_writing_an_undeclared_output(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    stage = _FakeStage(folder)
    guard = declared_io_for(stage, folder)

    with pytest.raises(FolderError):
        guard.write_text(folder.spec_guidelines_md, "should not be allowed")


def test_stage_result_can_carry_new_blocking_questions() -> None:
    result = StageResult(outputs_written=[], blocking_questions=["[high] auth: cookies or JWT?"])
    assert result.blocking_questions == ["[high] auth: cookies or JWT?"]


def test_stage_result_defaults_to_no_blocking_questions() -> None:
    result = StageResult(outputs_written=[])
    assert result.blocking_questions == []
