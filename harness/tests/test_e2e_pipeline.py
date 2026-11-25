"""End-to-end pipeline test (T-240): the whole orchestrator across
`concept -> guidelines -> freeze -> tickets -> implement`, with no real
models, containers, or spend — the workhorse test that proves the v0
skeleton actually walks (guidelines §4.3).
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.claude_code import ReviewResult
from harness.adapters.coding import AgentResult
from harness.adapters.text import GenerationResult, TokenUsage
from harness.budget import BudgetGuard
from harness.config import load_config
from harness.core.clock import FrozenClock
from harness.core.errors import BudgetExceeded, GateRejected
from harness.folder import ProjectFolder
from harness.freeze import latest_version
from harness.gates import GateIO, GateResponse
from harness.journal import read_decisions, read_progress
from harness.orchestrator import Orchestrator
from harness.sandbox import CommandResult, Sandbox
from tests.fakes.fake_coding import FakeCodingAgent, ScriptedRun
from tests.fakes.fake_text import FakeTextAdapter

FIXED = datetime(2026, 1, 1, tzinfo=UTC)

NO_BLOCKING = "## Decisions needed (blocking)\n"

READY_CONCEPT = """# Concept

## Components
Auth service, API gateway.

## Data Model
User, Project.

## External Interfaces
REST API.

## Technology Stack
Python, Postgres.

## Data and Control Flows
Request flows through the gateway.

## Phasing
No phasing is needed for this project.
"""

PHASED_CONCEPT = READY_CONCEPT.replace(
    "No phasing is needed for this project.",
    "```yaml\nphases:\n  - id: phase-1\n    name: MVP\n    scope: core\n    active: true\n"
    "stop_after_active_phase: true\n```",
)

GUIDELINES_TEXT = "# Guidelines\n\nTest-first, typed, small modules."
CONSOLIDATION_NO_CONFLICT = (
    '{"conflict_found": false, "conflict": null, "resolution": null, "revised_concept": null}'
)

TICKETS_RESPONSE = """
## TICKET: 000-overview
### Goal
Index ticket: dependency graph and build order.

## TICKET: 010-thing
### Goal
Implement the first thing.

### Connections
- depends on:
"""

CONFIG_YAML = """
project:
  name: e2e-project
  root: .
  requirements: requirements.md

models:
  concept:    { provider: anthropic, model: claude-opus-4-8 }
  guidelines: { provider: anthropic, model: claude-sonnet-4-6 }
  tickets:    { provider: anthropic, model: claude-opus-4-8 }
  implement:  { agent: claude-code,  model: claude-sonnet-4-6 }
  review:     { agent: claude-code,  model: claude-opus-4-8 }

gates:
  concept: auto_approve
  guidelines: auto_approve
  tickets: auto_approve
  phase_boundary: stop

budget:
  max_usd_per_run: 1000
  warn_at_usd: 900
"""


class FakeSandbox(Sandbox):
    """Confinement behaves for real (pure path logic); command execution
    never touches Docker — automated checks always report green."""

    def run(self, command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        return CommandResult(exit_code=0, stdout=f"{command[0]} ok", stderr="")


class AlwaysPassReviewer:
    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewResult:
        return ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))


def text_script(concept_text: str = READY_CONCEPT) -> list[GenerationResult | Exception]:
    return [
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),  # brainstorm
        GenerationResult(text=concept_text, usage=TokenUsage(10, 10)),  # concept write
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),  # self-review
        GenerationResult(text=GUIDELINES_TEXT, usage=TokenUsage(10, 10)),  # guidelines
        GenerationResult(text=CONSOLIDATION_NO_CONFLICT, usage=TokenUsage(10, 10)),
        GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10)),  # tickets
    ]


def coding_script() -> list[ScriptedRun | Exception]:
    return [
        ScriptedRun(
            result=AgentResult(
                success=True, summary="implemented", usage=TokenUsage(1, 1), cost_usd=0.0
            )
        ),
        ScriptedRun(
            result=AgentResult(
                success=True, summary="matches requirements", usage=TokenUsage(1, 1), cost_usd=0.0
            )
        ),
    ]


def build_orchestrator(
    tmp_path: Path,
    *,
    config_text: str = CONFIG_YAML,
    concept_text: str = READY_CONCEPT,
    max_usd_per_run: float | None = None,
    gate_io: GateIO | None = None,
    text_script_override: list[GenerationResult | Exception] | None = None,
) -> tuple[Orchestrator, ProjectFolder, FakeTextAdapter, FakeCodingAgent]:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build an authenticated project API")
    config_path = tmp_path / "harness.config.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    config = load_config(config_path)

    text_adapter = FakeTextAdapter(script=text_script_override or text_script(concept_text))
    coding_agent = FakeCodingAgent(script=coding_script())
    budget = BudgetGuard(
        max_usd_per_run=max_usd_per_run or config.budget.max_usd_per_run,
        warn_at_usd=config.budget.warn_at_usd,
    )

    def default_io(artifact: str) -> GateResponse:
        return GateResponse(decision="approve")

    io = gate_io if gate_io is not None else default_io

    orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=coding_agent,
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=FakeSandbox(root=tmp_path),
        gate_io=io,
        ask_user=lambda _q: "n/a",
        budget_guard=budget,
    )
    return orchestrator, folder, text_adapter, coding_agent


def test_full_pipeline_runs_green_end_to_end_with_no_phasing(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = build_orchestrator(tmp_path)

    result = orchestrator.run()

    assert result.halted is False
    assert folder.spec_concept_md.exists()
    assert folder.spec_open_questions_md.exists()
    assert folder.spec_phasing_yaml.exists()
    assert folder.spec_guidelines_md.exists()
    assert (folder.spec_tickets_dir / "000-overview.md").exists()
    assert (tmp_path / "tickets.zip").exists()
    assert latest_version(folder) is not None

    progress = read_progress(folder)
    assert {e.ticket for e in progress} == {"T-010", "__final_acceptance__"}
    assert read_decisions(folder) == []  # no concept/guidelines conflict in this run


def test_crash_and_resume_continues_from_first_incomplete_unit(tmp_path: Path) -> None:
    # First run completes the spec stages; simulate a crash before implementation
    # by handing the orchestrator a coding agent with an empty script up front.
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    config_path = tmp_path / "harness.config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    config = load_config(config_path)

    text_adapter = FakeTextAdapter(script=text_script())
    crashing_orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=FakeCodingAgent(script=[]),  # crashes on first implement call
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=FakeSandbox(root=tmp_path),
        gate_io=lambda artifact: GateResponse(decision="approve"),
        ask_user=lambda _q: "n/a",
        budget_guard=BudgetGuard(max_usd_per_run=1000, warn_at_usd=900),
    )
    with pytest.raises(Exception):  # noqa: B017, PT011 -- the fake's exhausted-script error
        crashing_orchestrator.run()

    # spec stages already completed and frozen before the crash
    assert folder.spec_concept_md.exists()
    assert folder.spec_guidelines_md.exists()
    assert (folder.spec_tickets_dir / "000-overview.md").exists()
    version_before_resume = latest_version(folder)

    # resume: a fresh orchestrator with a coding agent that can finish the job
    resumed_coding_agent = FakeCodingAgent(script=coding_script())
    resumed_orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=resumed_coding_agent,
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=FakeSandbox(root=tmp_path),
        gate_io=lambda artifact: GateResponse(decision="approve"),
        ask_user=lambda _q: "n/a",
        budget_guard=BudgetGuard(max_usd_per_run=1000, warn_at_usd=900),
    )

    result = resumed_orchestrator.run()

    assert result.halted is False
    assert latest_version(folder) == version_before_resume  # not re-frozen
    assert {e.ticket for e in read_progress(folder)} == {"T-010", "__final_acceptance__"}


def test_budget_exceeded_halts_the_pipeline_mid_run(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = build_orchestrator(tmp_path, max_usd_per_run=0.000001)

    with pytest.raises(BudgetExceeded):
        orchestrator.run()

    assert not folder.spec_guidelines_md.exists()


def test_gate_rejection_halts_the_pipeline(tmp_path: Path) -> None:
    # a rejection triggers one regeneration attempt (T-320); since gate_io
    # rejects unconditionally, the *second* rejection is the one that halts —
    # so the concept-stage's three calls (brainstorm/write/self-review) are
    # scripted twice.
    interactive_config = CONFIG_YAML.replace("concept: auto_approve", "concept: interactive")
    concept_round = text_script()[:3]
    orchestrator, folder, _text, _coding = build_orchestrator(
        tmp_path,
        config_text=interactive_config,
        gate_io=lambda artifact: GateResponse(decision="reject", feedback="needs work"),
        text_script_override=concept_round + concept_round,
    )

    with pytest.raises(GateRejected):
        orchestrator.run()

    assert not folder.spec_guidelines_md.exists()


def test_gate_approve_path_proceeds(tmp_path: Path) -> None:
    interactive_config = CONFIG_YAML.replace("concept: auto_approve", "concept: interactive")
    orchestrator, folder, _text, _coding = build_orchestrator(
        tmp_path,
        config_text=interactive_config,
        gate_io=lambda artifact: GateResponse(decision="approve"),
    )

    result = orchestrator.run()

    assert result.halted is False
    assert folder.spec_guidelines_md.exists()


def test_auto_approve_gate_path_never_prompts(tmp_path: Path) -> None:
    prompted: list[str] = []

    def spy_io(artifact: str) -> GateResponse:
        prompted.append(artifact)
        return GateResponse(decision="approve")

    orchestrator, _folder, _text, _coding = build_orchestrator(tmp_path, gate_io=spy_io)
    orchestrator.run()

    assert prompted == []  # gates.concept/guidelines/tickets are all auto_approve


def test_phase_stop_halts_after_implementing_the_active_phase(tmp_path: Path) -> None:
    # concept §6.3/§11: implement the active phase, *then* stop at the
    # boundary — implementation must not be skipped entirely.
    orchestrator, _folder, _text, coding_agent = build_orchestrator(
        tmp_path, concept_text=PHASED_CONCEPT
    )

    result = orchestrator.run()

    assert result.halted is True
    assert result.halt_reason == "phase_boundary"
    assert "implement" in result.completed_stages
    assert len(coding_agent.calls) > 0
