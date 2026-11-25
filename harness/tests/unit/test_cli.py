"""CLI integration tests (T-230), using typer's CliRunner against the
orchestrator with fakes (`build_orchestrator` monkeypatched)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import harness.cli as cli_module
from harness.cli import app
from harness.config import HarnessConfig
from harness.core.clock import Clock
from harness.folder import ProjectFolder
from harness.journal import (
    DecisionRecord,
    GateOutcome,
    ProgressEntry,
    RunLogEntry,
    append_run_log,
    record_decision,
    record_gate_outcome,
    record_progress,
)
from harness.orchestrator import OrchestratorResult

runner = CliRunner()

FIXED = datetime(2026, 1, 1, tzinfo=UTC)

VALID_CONFIG = """
project:
  name: test-project
  root: .
  requirements: requirements.md

models:
  concept:    { provider: anthropic, model: claude-opus-4-8 }
  guidelines: { provider: anthropic, model: claude-sonnet-4-6 }
  tickets:    { provider: anthropic, model: claude-opus-4-8 }
  implement:  { agent: claude-code,  model: claude-sonnet-4-6 }
  review:     { agent: claude-code,  model: claude-opus-4-8 }
"""


class StubOrchestrator:
    def __init__(self, result: OrchestratorResult) -> None:
        self._result = result
        self.invalidated_from: str | None = None

    def run(self) -> OrchestratorResult:
        return self._result

    def invalidate_from(self, stage: str) -> None:
        self.invalidated_from = stage


def seed_project(tmp_path: Path) -> ProjectFolder:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.harness_config_yaml, VALID_CONFIG)
    return folder


def test_run_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_project(tmp_path)
    stub_result = OrchestratorResult(
        completed_stages=["concept", "guidelines", "freeze", "tickets", "implement"],
        halted=False,
        halt_reason=None,
    )

    def fake_build_orchestrator(
        folder: ProjectFolder, config: HarnessConfig, clock: Clock
    ) -> StubOrchestrator:
        return StubOrchestrator(stub_result)

    monkeypatch.setattr(cli_module, "build_orchestrator", fake_build_orchestrator)

    result = runner.invoke(app, ["run", "--project", str(tmp_path)])

    assert result.exit_code == 0
    assert "implement" in result.stdout


def test_run_with_final_acceptance_drift_exits_with_a_distinct_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_project(tmp_path)
    stub_result = OrchestratorResult(
        completed_stages=["concept", "guidelines", "freeze", "tickets", "implement"],
        halted=False,
        halt_reason=None,
        warnings=["Final acceptance pass found drift: missing a page"],
    )

    def fake_build_orchestrator(
        folder: ProjectFolder, config: HarnessConfig, clock: Clock
    ) -> StubOrchestrator:
        return StubOrchestrator(stub_result)

    monkeypatch.setattr(cli_module, "build_orchestrator", fake_build_orchestrator)

    result = runner.invoke(app, ["run", "--project", str(tmp_path)])

    assert result.exit_code == 4
    assert "drift" in result.stdout.lower()
    assert "missing a page" in result.stdout


def test_run_halts_with_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_project(tmp_path)
    stub_result = OrchestratorResult(
        completed_stages=["concept", "guidelines", "freeze", "tickets"],
        halted=True,
        halt_reason="phase_boundary",
    )

    def fake_build_orchestrator(
        folder: ProjectFolder, config: HarnessConfig, clock: Clock
    ) -> StubOrchestrator:
        return StubOrchestrator(stub_result)

    monkeypatch.setattr(cli_module, "build_orchestrator", fake_build_orchestrator)

    result = runner.invoke(app, ["run", "--project", str(tmp_path)])

    assert result.exit_code == 2
    assert "phase_boundary" in result.stdout


def test_run_with_valid_from_stage_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_project(tmp_path)
    stub_result = OrchestratorResult(completed_stages=["implement"], halted=False, halt_reason=None)
    stubs: list[StubOrchestrator] = []

    def fake_build_orchestrator(
        folder: ProjectFolder, config: HarnessConfig, clock: Clock
    ) -> StubOrchestrator:
        stub = StubOrchestrator(stub_result)
        stubs.append(stub)
        return stub

    monkeypatch.setattr(cli_module, "build_orchestrator", fake_build_orchestrator)

    result = runner.invoke(app, ["run", "--project", str(tmp_path), "--from", "tickets"])

    assert result.exit_code == 0
    assert stubs[0].invalidated_from == "tickets"


def test_run_with_invalid_from_stage_exits_nonzero(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(app, ["run", "--project", str(tmp_path), "--from", "bogus-stage"])
    assert result.exit_code == 1


def test_status_prints_progress_and_decisions(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-010", summary="scaffolding"))
    record_decision(
        folder,
        DecisionRecord(
            timestamp=FIXED,
            ticket="T-090",
            conflict="x",
            resolution="y wins",
            reasoning="concept wins",
        ),
    )

    result = runner.invoke(app, ["status", "--project", str(tmp_path)])

    assert result.exit_code == 0
    assert "T-010" in result.stdout
    assert "y wins" in result.stdout


def test_status_shows_open_escalations_before_progress(tmp_path: Path) -> None:
    from harness.journal import EscalationRecord, record_escalation

    folder = seed_project(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="failed 3 times"
        ),
    )

    result = runner.invoke(app, ["status", "--project", str(tmp_path)])

    assert result.exit_code == 0
    assert "Open escalations" in result.stdout
    assert "failed 3 times" in result.stdout
    assert result.stdout.index("Open escalations") < result.stdout.index("Progress:")


def test_resolve_answers_an_open_escalation(tmp_path: Path) -> None:
    from harness.journal import EscalationRecord, latest_escalation_for, record_escalation

    folder = seed_project(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="failed 3 times"
        ),
    )

    result = runner.invoke(
        app, ["resolve", "--project", str(tmp_path), "--ticket", "T-010", "--answer", "use lib X"]
    )

    assert result.exit_code == 0
    escalation = latest_escalation_for(folder, "T-010")
    assert escalation is not None
    assert escalation.resolution == "use lib X"


def test_resolve_with_no_open_escalation_exits_nonzero(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(
        app, ["resolve", "--project", str(tmp_path), "--ticket", "T-010", "--answer", "x"]
    )
    assert result.exit_code == 1


def _seed_run_log_entry(folder: ProjectFolder, **overrides: object) -> None:
    defaults: dict[str, object] = {
        "timestamp": FIXED,
        "stage": "concept",
        "provider_or_agent": "anthropic",
        "model": "claude-opus-4-8",
        "prompt_template": "concept-write",
        "prompt_version": "v1",
        "input_tokens": 100,
        "output_tokens": 200,
        "estimated_cost_usd": 0.05,
        "wall_time_s": 1.2,
    }
    defaults.update(overrides)
    append_run_log(folder, RunLogEntry.model_validate(defaults))


def test_status_with_no_run_log_shows_no_runs_recorded(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(app, ["status", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "no runs recorded" in result.stdout.lower()


def test_status_shows_total_and_per_stage_spend(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    _seed_run_log_entry(folder, stage="concept", estimated_cost_usd=0.05)
    _seed_run_log_entry(folder, stage="concept", estimated_cost_usd=0.03)
    _seed_run_log_entry(folder, stage="guidelines", estimated_cost_usd=0.10)

    result = runner.invoke(app, ["status", "--project", str(tmp_path)])

    assert result.exit_code == 0
    assert "$0.1800" in result.stdout
    assert "concept: $0.0800" in result.stdout
    assert "guidelines: $0.1000" in result.stdout


def test_status_shows_pipeline_gate_positions(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    record_gate_outcome(
        folder,
        GateOutcome(timestamp=FIXED, stage="concept", decision="approve", artifact_hash="h1"),
    )

    result = runner.invoke(app, ["status", "--project", str(tmp_path)])

    assert result.exit_code == 0
    assert "concept: approve" in result.stdout
    assert "guidelines: pending" in result.stdout
    assert "tickets: pending" in result.stdout
    assert "implement: pending" in result.stdout


def test_log_with_no_run_log_shows_no_runs_recorded(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(app, ["log", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "no runs recorded" in result.stdout.lower()


def test_log_tail_and_stage_filter_show_the_right_entries(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    for i in range(5):
        _seed_run_log_entry(
            folder, stage="tickets", prompt_template="tickets-write", estimated_cost_usd=0.01 * i
        )
    _seed_run_log_entry(folder, stage="concept")

    result = runner.invoke(
        app, ["log", "--project", str(tmp_path), "--tail", "3", "--stage", "tickets"]
    )

    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    assert all("[tickets]" in line for line in lines)
    assert "$0.0400" in lines[-1]


def test_gate_approve(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")

    result = runner.invoke(
        app, ["gate", "--project", str(tmp_path), "--stage", "concept", "--approve"]
    )

    assert result.exit_code == 0
    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept v1"


def test_gate_edit(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    edit_file = tmp_path / "edited.md"
    edit_file.write_text("# Concept v2", encoding="utf-8")

    result = runner.invoke(
        app,
        ["gate", "--project", str(tmp_path), "--stage", "concept", "--edit", str(edit_file)],
    )

    assert result.exit_code == 0
    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept v2"


def test_gate_reject_exits_nonzero(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")

    result = runner.invoke(
        app,
        [
            "gate",
            "--project",
            str(tmp_path),
            "--stage",
            "concept",
            "--reject",
            "not detailed enough",
        ],
    )

    assert result.exit_code == 3
    assert "not detailed enough" in result.stdout


def test_gate_with_no_decision_flag_exits_nonzero(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(app, ["gate", "--project", str(tmp_path), "--stage", "concept"])
    assert result.exit_code == 1


def test_gate_with_unknown_stage_exits_nonzero(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(
        app, ["gate", "--project", str(tmp_path), "--stage", "bogus", "--approve"]
    )
    assert result.exit_code == 1


def _seed_phased_project(tmp_path: Path) -> ProjectFolder:
    folder = seed_project(tmp_path)
    folder.write_text(
        folder.spec_phasing_yaml,
        "phases:\n"
        "  - id: phase-1\n    name: MVP\n    active: true\n"
        "  - id: phase-2\n    name: Later\n    active: false\n"
        "stop_after_active_phase: true\n",
    )
    folder.write_text(folder.spec_tickets_dir / "010-thing.md", "# T-010\n")
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-010", summary="done"))
    folder.write_text(
        folder.spec_tickets_deferred_phase_dir("phase-2") / "020-later.md", "# T-020\n"
    )
    return folder


def test_phase_next_promotes_deferred_tickets_after_active_phase_completes(
    tmp_path: Path,
) -> None:
    folder = _seed_phased_project(tmp_path)

    result = runner.invoke(app, ["phase", "--project", str(tmp_path), "--next"])

    assert result.exit_code == 0
    assert (folder.spec_tickets_dir / "020-later.md").exists()
    assert not (folder.spec_tickets_deferred_phase_dir("phase-2") / "020-later.md").exists()
    phasing = folder.read_text(folder.spec_phasing_yaml) or ""
    assert "phase-2" in phasing


def test_phase_next_refuses_while_the_active_phase_is_incomplete(tmp_path: Path) -> None:
    folder = seed_project(tmp_path)
    folder.write_text(
        folder.spec_phasing_yaml,
        "phases:\n"
        "  - id: phase-1\n    name: MVP\n    active: true\n"
        "  - id: phase-2\n    name: Later\n    active: false\n"
        "stop_after_active_phase: true\n",
    )
    folder.write_text(folder.spec_tickets_dir / "010-thing.md", "# T-010\n")
    # no progress recorded for T-010 — the phase isn't complete

    result = runner.invoke(app, ["phase", "--project", str(tmp_path), "--next"])

    assert result.exit_code == 1


def test_phase_next_refuses_with_open_escalations(tmp_path: Path) -> None:
    from harness.journal import EscalationRecord, record_escalation

    folder = _seed_phased_project(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="x"),
    )

    result = runner.invoke(app, ["phase", "--project", str(tmp_path), "--next"])

    assert result.exit_code == 1
    assert not (folder.spec_tickets_dir / "020-later.md").exists()


def test_phase_activate_a_specific_phase_id(tmp_path: Path) -> None:
    folder = _seed_phased_project(tmp_path)

    result = runner.invoke(app, ["phase", "--project", str(tmp_path), "--activate", "phase-2"])

    assert result.exit_code == 0
    assert (folder.spec_tickets_dir / "020-later.md").exists()


def test_phase_requires_exactly_one_of_next_or_activate(tmp_path: Path) -> None:
    _seed_phased_project(tmp_path)
    result = runner.invoke(app, ["phase", "--project", str(tmp_path)])
    assert result.exit_code == 1

    result = runner.invoke(
        app, ["phase", "--project", str(tmp_path), "--next", "--activate", "phase-2"]
    )
    assert result.exit_code == 1


def test_phase_with_no_phasing_declared_exits_nonzero(tmp_path: Path) -> None:
    seed_project(tmp_path)
    result = runner.invoke(app, ["phase", "--project", str(tmp_path), "--next"])
    assert result.exit_code == 1
