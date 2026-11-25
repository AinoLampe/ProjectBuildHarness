"""Fake-adapter driven end-to-end tests for Stage 1a (T-170)."""

from pathlib import Path

import pytest

from harness.adapters.text import GenerationResult, TokenUsage
from harness.core.errors import FolderError, StageError
from harness.folder import ProjectFolder
from harness.stages.concept import ConceptStage
from tests.fakes.fake_text import FakeTextAdapter

NO_BLOCKING_QUESTIONS = """
## Assumptions (proceeding unless corrected)
- [low] Single relational DB.

## Decisions needed (blocking)

## Suggested improvements (optional)
- [low] Add caching.
"""

WITH_BLOCKING_QUESTIONS = """
## Assumptions (proceeding unless corrected)
- [low] Single relational DB.

## Decisions needed (blocking)
- [high] Auth: cookies or JWT?

## Suggested improvements (optional)
"""

READY_CONCEPT_WITH_PHASING = """# Concept

## Components
Auth service, API gateway.

## Data Model
User, Project entities.

## External Interfaces
REST API.

## Technology Stack
Python, Postgres.

## Data and Control Flows
Request flows through the gateway.

## Phasing
```yaml
phases:
  - id: phase-1
    name: MVP
    scope: core
    active: true
stop_after_active_phase: true
```
"""

NOT_READY_CONCEPT = "# Concept\n\nJust prose, no structure at all.\n"


def gen(text: str) -> GenerationResult:
    return GenerationResult(text=text, usage=TokenUsage(10, 20))


def test_concept_stage_emits_exactly_its_declared_outputs(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    adapter = FakeTextAdapter(
        script=[
            gen(NO_BLOCKING_QUESTIONS),  # brainstorm
            gen(READY_CONCEPT_WITH_PHASING),  # concept write
            gen(NO_BLOCKING_QUESTIONS),  # self-review
        ]
    )
    stage = ConceptStage(
        folder=folder, max_rounds=3, ask_user=lambda _q: pytest.fail("should not be asked")
    )

    result = stage.run(folder, adapter, rendered_prompt="")

    assert set(result.outputs_written) == {
        folder.spec_open_questions_md,
        folder.spec_concept_md,
        folder.spec_phasing_yaml,
    }
    assert folder.spec_concept_md.exists()
    assert folder.spec_open_questions_md.exists()
    assert folder.spec_phasing_yaml.exists()
    # declared-IO: nothing else under spec/ was written
    assert sorted(p.name for p in folder.spec_dir.iterdir() if p.is_file()) == [
        "concept.md",
        "open-questions.md",
        "phasing.yaml",
    ]


def test_concept_stage_round_cap_exhaustion_records_documented_assumptions(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    adapter = FakeTextAdapter(
        script=[
            gen(WITH_BLOCKING_QUESTIONS),  # brainstorm round 1
            gen(WITH_BLOCKING_QUESTIONS),  # brainstorm round 2 (cap=2 -> exhausted here)
            gen(READY_CONCEPT_WITH_PHASING),  # concept write
            gen(NO_BLOCKING_QUESTIONS),  # self-review
        ]
    )
    asked: list[str] = []
    stage = ConceptStage(
        folder=folder,
        max_rounds=2,
        ask_user=lambda q: (asked.append(q), "an answer")[1],
    )

    result = stage.run(folder, adapter, rendered_prompt="")

    assert len(asked) == 2  # the user gets exactly max_rounds opportunities (T-350)
    assert result.outputs_written  # terminated, did not loop forever


def test_concept_stage_self_review_can_re_enter_the_loop(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    adapter = FakeTextAdapter(
        script=[
            gen(NO_BLOCKING_QUESTIONS),  # brainstorm
            gen(READY_CONCEPT_WITH_PHASING),  # concept write
            gen(WITH_BLOCKING_QUESTIONS),  # self-review round 1: new blocking question
            gen(NO_BLOCKING_QUESTIONS),  # self-review round 2: resolved
            gen(READY_CONCEPT_WITH_PHASING + "\n## Revised\nIncorporated feedback."),  # revision
        ]
    )
    asked: list[str] = []
    stage = ConceptStage(
        folder=folder, max_rounds=3, ask_user=lambda q: (asked.append(q), "resolved")[1]
    )

    stage.run(folder, adapter, rendered_prompt="")

    assert len(asked) == 1
    concept_text = folder.spec_concept_md.read_text(encoding="utf-8")
    assert "Incorporated feedback" in concept_text


def test_concept_not_ready_raises_stage_error(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    adapter = FakeTextAdapter(
        script=[
            gen(NO_BLOCKING_QUESTIONS),  # brainstorm
            gen(NOT_READY_CONCEPT),  # concept write — fails the readiness checklist
            gen(NO_BLOCKING_QUESTIONS),  # self-review
        ]
    )
    stage = ConceptStage(folder=folder, max_rounds=3, ask_user=lambda _q: "n/a")

    with pytest.raises(StageError):
        stage.run(folder, adapter, rendered_prompt="")


def test_concept_stage_input_is_only_requirements_and_instructions(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.spec_guidelines_md, "must not be read by stage 1a")
    adapter = FakeTextAdapter(
        script=[
            gen(NO_BLOCKING_QUESTIONS),
            gen(READY_CONCEPT_WITH_PHASING),
            gen(NO_BLOCKING_QUESTIONS),
        ]
    )
    stage = ConceptStage(folder=folder, max_rounds=3, ask_user=lambda _q: "n/a")
    stage.run(folder, adapter, rendered_prompt="")

    for _prompt, files in adapter.calls:
        assert "guidelines.md" not in files


def test_concept_stage_with_no_phasing_needed(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    no_phasing_concept = READY_CONCEPT_WITH_PHASING.replace(
        "```yaml\nphases:\n  - id: phase-1\n    name: MVP\n    scope: core\n    active: true\n"
        "stop_after_active_phase: true\n```",
        "No phasing is needed for this small project.",
    )
    adapter = FakeTextAdapter(
        script=[
            gen(NO_BLOCKING_QUESTIONS),
            gen(no_phasing_concept),
            gen(NO_BLOCKING_QUESTIONS),
        ]
    )
    stage = ConceptStage(folder=folder, max_rounds=3, ask_user=lambda _q: "n/a")
    stage.run(folder, adapter, rendered_prompt="")

    phasing = folder.spec_phasing_yaml.read_text(encoding="utf-8")
    assert "phases: []" in phasing


def test_writing_an_undeclared_output_is_rejected_by_the_guard(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    stage = ConceptStage(folder=folder, max_rounds=3, ask_user=lambda _q: "n/a")
    from harness.stages.base import declared_io_for

    guard = declared_io_for(stage, folder)
    with pytest.raises(FolderError):
        guard.write_text(folder.spec_guidelines_md, "not allowed")
