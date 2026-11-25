"""Fake-adapter driven end-to-end tests for Stage 2 (T-190)."""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.text import GenerationResult, TokenUsage
from harness.core.clock import FrozenClock
from harness.core.errors import DagCycleError, StageError
from harness.folder import ProjectFolder
from harness.freeze import freeze_spec
from harness.stages.tickets import TicketsStage
from tests.fakes.fake_text import FakeTextAdapter

FIXED = datetime(2026, 1, 1, tzinfo=UTC)

RESPONSE = """
## TICKET: 000-overview
### Goal
Index ticket: dependency graph, build order, conventions.

## TICKET: 010-scaffolding
### Goal
Stand up the repo.

### Connections
- depends on:
- blocks: 020

## TICKET: 020-core
### Goal
Core primitives.

### Connections
- depends on: 010
"""

CYCLIC_RESPONSE = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-a
### Connections
- depends on: 020

## TICKET: 020-b
### Connections
- depends on: 010
"""

PHASED_RESPONSE = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-phase-one
### Phase
phase-1

### Connections
- depends on:

## TICKET: 020-phase-two
### Phase
phase-2

### Connections
- depends on:
"""


def setup_frozen_project(
    tmp_path: Path,
    *,
    phasing_yaml: str = "phases: []\nstop_after_active_phase: false\n",
) -> tuple[ProjectFolder, str]:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept")
    folder.write_text(folder.spec_guidelines_md, "# Guidelines")
    folder.write_text(folder.spec_phasing_yaml, phasing_yaml)
    frozen = freeze_spec(folder, FrozenClock(FIXED))
    return folder, frozen.version


def test_overview_is_written_first_and_tickets_follow_schema(tmp_path: Path) -> None:
    folder, version = setup_frozen_project(tmp_path)
    adapter = FakeTextAdapter(script=[GenerationResult(text=RESPONSE, usage=TokenUsage(1, 1))])
    stage = TicketsStage(folder=folder, frozen_version=version, clock=FrozenClock(FIXED))

    result = stage.run(folder, adapter, rendered_prompt="")

    overview = folder.spec_tickets_dir / "000-overview.md"
    assert overview.exists()
    assert overview in result.outputs_written
    assert (folder.spec_tickets_dir / "010-scaffolding.md").exists()
    assert (folder.spec_tickets_dir / "020-core.md").exists()


def test_tickets_zip_is_produced(tmp_path: Path) -> None:
    folder, version = setup_frozen_project(tmp_path)
    adapter = FakeTextAdapter(script=[GenerationResult(text=RESPONSE, usage=TokenUsage(1, 1))])
    stage = TicketsStage(folder=folder, frozen_version=version, clock=FrozenClock(FIXED))
    stage.run(folder, adapter, rendered_prompt="")

    zip_path = folder.root / "tickets.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "000-overview.md" in names
    assert "010-scaffolding.md" in names


def test_cyclic_ticket_dag_raises_dag_cycle_error(tmp_path: Path) -> None:
    folder, version = setup_frozen_project(tmp_path)
    adapter = FakeTextAdapter(
        script=[GenerationResult(text=CYCLIC_RESPONSE, usage=TokenUsage(1, 1))]
    )
    stage = TicketsStage(folder=folder, frozen_version=version, clock=FrozenClock(FIXED))

    with pytest.raises(DagCycleError):
        stage.run(folder, adapter, rendered_prompt="")


def test_only_active_phase_tickets_are_written(tmp_path: Path) -> None:
    phasing_yaml = (
        "phases:\n"
        "  - id: phase-1\n    name: MVP\n    scope: core\n    active: true\n"
        "  - id: phase-2\n    name: Later\n    scope: extra\n    active: false\n"
        "stop_after_active_phase: true\n"
    )
    folder, version = setup_frozen_project(tmp_path, phasing_yaml=phasing_yaml)
    adapter = FakeTextAdapter(
        script=[GenerationResult(text=PHASED_RESPONSE, usage=TokenUsage(1, 1))]
    )
    stage = TicketsStage(folder=folder, frozen_version=version, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    assert (folder.spec_tickets_dir / "010-phase-one.md").exists()
    assert not (folder.spec_tickets_dir / "020-phase-two.md").exists()

    # T-540: the deferred ticket is archived, not discarded
    deferred_path = folder.spec_tickets_deferred_phase_dir("phase-2") / "020-phase-two.md"
    assert deferred_path.exists()

    with zipfile.ZipFile(folder.root / "tickets.zip") as archive:
        names = set(archive.namelist())
    assert "010-phase-one.md" in names
    assert "020-phase-two.md" not in names  # deferred tickets excluded from the zip


def test_reads_the_frozen_spec_not_a_live_copy(tmp_path: Path) -> None:
    folder, version = setup_frozen_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v2 — changed after freeze")
    adapter = FakeTextAdapter(script=[GenerationResult(text=RESPONSE, usage=TokenUsage(1, 1))])
    stage = TicketsStage(folder=folder, frozen_version=version, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    _prompt, files = adapter.calls[0]
    assert files["concept.md"] == "# Concept"
    assert "v2" not in files["concept.md"]


def test_stale_frozen_version_is_rejected(tmp_path: Path) -> None:
    # a later freeze supersedes the version this stage was constructed with
    folder, old_version = setup_frozen_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v2")
    freeze_spec(folder, FrozenClock(FIXED.replace(minute=5)))

    adapter = FakeTextAdapter(script=[GenerationResult(text=RESPONSE, usage=TokenUsage(1, 1))])
    stage = TicketsStage(folder=folder, frozen_version=old_version, clock=FrozenClock(FIXED))

    with pytest.raises(StageError, match="superseded"):
        stage.run(folder, adapter, rendered_prompt="")
