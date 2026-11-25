"""Behavioural tests for the orchestrator state machine (T-220), driven
entirely with fakes (no real models, containers, or spend)."""

import hashlib
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
from harness.gates import GateResponse
from harness.journal import GateOutcome, read_progress, read_run_log, record_gate_outcome
from harness.orchestrator import Orchestrator
from harness.sandbox import CommandResult, Sandbox
from tests.fakes.fake_coding import FakeCodingAgent, ScriptedRun
from tests.fakes.fake_text import FakeTextAdapter

FIXED = datetime(2026, 1, 1, tzinfo=UTC)

NO_BLOCKING = """
## Decisions needed (blocking)
"""

READY_CONCEPT = """# Concept

## Components
A, B.

## Data Model
User.

## External Interfaces
REST.

## Technology Stack
Python.

## Data and Control Flows
Flow.

## Phasing
No phasing is needed for this project.
"""

GUIDELINES_TEXT = "# Guidelines\n\nBest practices."
CONSOLIDATION_NO_CONFLICT = (
    '{"conflict_found": false, "conflict": null, "resolution": null, "revised_concept": null}'
)

TICKETS_RESPONSE = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-thing
### Goal
Do the thing.

### Connections
- depends on:
"""

CONFIG_YAML = """
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

gates:
  concept: auto_approve
  guidelines: auto_approve
  tickets: auto_approve
  phase_boundary: stop

budget:
  max_usd_per_run: 1000
  warn_at_usd: 900
"""


class ScriptedSandbox(Sandbox):
    def run(self, command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        return CommandResult(exit_code=0, stdout="ok", stderr="")


class AlwaysPassReviewer:
    def __init__(self) -> None:
        self.calls = 0

    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewResult:
        self.calls += 1
        return ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))


def setup_orchestrator(
    tmp_path: Path, *, config_text: str = CONFIG_YAML, concept_text: str = READY_CONCEPT
) -> tuple[Orchestrator, ProjectFolder, FakeTextAdapter, FakeCodingAgent]:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    config_path = tmp_path / "harness.config.yaml"
    config_path.write_text(config_text, encoding="utf-8")
    config = load_config(config_path)

    text_adapter = FakeTextAdapter(
        script=[
            GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),  # brainstorm
            GenerationResult(text=concept_text, usage=TokenUsage(10, 10)),  # concept write
            GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),  # self-review
            GenerationResult(text=GUIDELINES_TEXT, usage=TokenUsage(10, 10)),  # guidelines
            GenerationResult(
                text=CONSOLIDATION_NO_CONFLICT, usage=TokenUsage(10, 10)
            ),  # consolidation
            GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10)),  # tickets
        ]
    )
    coding_agent = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="implemented", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
        ]
    )
    sandbox = ScriptedSandbox(root=tmp_path)
    orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=coding_agent,
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=sandbox,
        gate_io=lambda artifact: GateResponse(decision="approve"),
        ask_user=lambda _q: "n/a",
        budget_guard=BudgetGuard(
            max_usd_per_run=config.budget.max_usd_per_run, warn_at_usd=config.budget.warn_at_usd
        ),
    )
    return orchestrator, folder, text_adapter, coding_agent


def test_full_sequence_runs_end_to_end_with_fakes(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)

    result = orchestrator.run()

    assert result.halted is False
    assert folder.spec_concept_md.exists()
    assert folder.spec_guidelines_md.exists()
    assert (folder.spec_tickets_dir / "000-overview.md").exists()
    assert len(read_progress(folder)) == 2  # one ticket + the final acceptance pass marker
    assert result.warnings == []


def test_final_acceptance_drift_surfaces_as_a_non_halting_warning(tmp_path: Path) -> None:
    class DriftDetectingReviewer:
        def review(
            self,
            ticket: str,
            diff_paths: list[Path],
            criteria: str,
            objective_results: str,
            prompt: str,
        ) -> ReviewResult:
            if ticket == "__final_acceptance__":
                return ReviewResult(
                    passed=False, reasons=["missing a page"], usage=TokenUsage(0, 0)
                )
            return ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))

    orchestrator, _folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.reviewer_adapter = DriftDetectingReviewer()

    result = orchestrator.run()

    assert result.halted is False  # drift does not halt the run
    assert result.warnings
    assert "missing a page" in result.warnings[0]


def test_idempotent_skip_on_unchanged_second_run_does_no_extra_work(tmp_path: Path) -> None:
    orchestrator, _folder, text_adapter, _coding_agent = setup_orchestrator(tmp_path)
    orchestrator.run()
    calls_after_first = len(text_adapter.calls)

    # second run must not call the (now-exhausted) script again — proves skip
    second_result = orchestrator.run()

    assert len(text_adapter.calls) == calls_after_first
    assert second_result.halted is False


def test_crash_and_resume_skips_completed_text_stages(tmp_path: Path) -> None:
    # simulate a crash after the concept stage (and its gate) already completed
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.spec_concept_md, READY_CONCEPT)
    folder.write_text(folder.spec_open_questions_md, NO_BLOCKING)
    folder.write_text(folder.spec_phasing_yaml, "phases: []\nstop_after_active_phase: false\n")
    record_gate_outcome(
        folder,
        GateOutcome(
            timestamp=FIXED,
            stage="concept",
            decision="approve",
            artifact_hash=hashlib.sha256(READY_CONCEPT.encode("utf-8")).hexdigest(),
        ),
    )

    config_path = tmp_path / "harness.config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    config = load_config(config_path)

    # only the calls needed from here on: guidelines, consolidation, tickets
    text_adapter = FakeTextAdapter(
        script=[
            GenerationResult(text=GUIDELINES_TEXT, usage=TokenUsage(10, 10)),
            GenerationResult(text=CONSOLIDATION_NO_CONFLICT, usage=TokenUsage(10, 10)),
            GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10)),
        ]
    )
    coding_agent = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="implemented", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
        ]
    )
    orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=coding_agent,
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=ScriptedSandbox(root=tmp_path),
        gate_io=lambda artifact: GateResponse(decision="approve"),
        ask_user=lambda _q: "n/a",
        budget_guard=BudgetGuard(max_usd_per_run=1000, warn_at_usd=900),
    )

    orchestrator.run()

    assert len(text_adapter.calls) == 3  # guidelines + consolidation + tickets — concept skipped


def test_budget_halt_before_exceeding_cap(tmp_path: Path) -> None:
    tight_config = CONFIG_YAML.replace(
        "max_usd_per_run: 1000\n  warn_at_usd: 900", "max_usd_per_run: 0.000001\n  warn_at_usd: 0"
    )
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path, config_text=tight_config)

    with pytest.raises(BudgetExceeded):
        orchestrator.run()

    assert not folder.spec_guidelines_md.exists()


def test_interactive_gate_rejection_halts_the_pipeline(tmp_path: Path) -> None:
    # a rejection triggers one regeneration attempt (T-320); since gate_io
    # rejects unconditionally, the *second* rejection is the one that halts —
    # so the concept round (brainstorm/write/self-review) is scripted twice.
    interactive_config = CONFIG_YAML.replace("concept: auto_approve", "concept: interactive")
    concept_round: list[GenerationResult | Exception] = [
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),
        GenerationResult(text=READY_CONCEPT, usage=TokenUsage(10, 10)),
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),
    ]
    orchestrator, folder, _text, _coding = setup_orchestrator(
        tmp_path, config_text=interactive_config
    )
    orchestrator.concept_adapter = FakeTextAdapter(script=concept_round + concept_round)
    orchestrator.gate_io = lambda artifact: GateResponse(decision="reject", feedback="not ready")

    with pytest.raises(GateRejected):
        orchestrator.run()

    assert not folder.spec_guidelines_md.exists()


def test_auto_approve_gate_never_calls_gate_io(tmp_path: Path) -> None:
    calls: list[str] = []
    orchestrator, _folder, _text, _coding = setup_orchestrator(tmp_path)

    def spy_gate_io(artifact: str) -> GateResponse:
        calls.append(artifact)
        return GateResponse(decision="approve")

    orchestrator.gate_io = spy_gate_io

    orchestrator.run()

    assert calls == []


def test_phase_boundary_stop_halts_after_implementing_the_active_phase(tmp_path: Path) -> None:
    # concept §6.3/§11: the harness implements the active phase, *then*
    # stops at the boundary — it must not skip implementation entirely.
    phased_concept = READY_CONCEPT.replace(
        "No phasing is needed for this project.",
        "```yaml\nphases:\n  - id: phase-1\n    name: MVP\n    scope: x\n    active: true\n"
        "stop_after_active_phase: true\n```",
    )
    orchestrator, _folder, _text, coding_agent = setup_orchestrator(
        tmp_path, concept_text=phased_concept
    )

    result = orchestrator.run()

    assert result.halted is True
    assert result.halt_reason == "phase_boundary"
    assert "implement" in result.completed_stages
    assert len(coding_agent.calls) > 0  # the active phase's ticket was implemented


def test_rejection_regenerates_once_with_feedback_then_a_second_rejection_halts(
    tmp_path: Path,
) -> None:
    interactive_config = CONFIG_YAML.replace("concept: auto_approve", "concept: interactive")
    concept_round: list[GenerationResult | Exception] = [
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),
        GenerationResult(text=READY_CONCEPT, usage=TokenUsage(10, 10)),
        GenerationResult(text=NO_BLOCKING, usage=TokenUsage(10, 10)),
    ]
    orchestrator, _folder, _text, _coding = setup_orchestrator(
        tmp_path, config_text=interactive_config
    )
    concept_adapter = FakeTextAdapter(script=concept_round + concept_round)
    orchestrator.concept_adapter = concept_adapter
    decisions = iter(["reject", "reject"])

    def gate_io(artifact: str) -> GateResponse:
        return GateResponse(decision="reject", feedback=f"attempt feedback: {next(decisions)}")

    orchestrator.gate_io = gate_io

    with pytest.raises(GateRejected):
        orchestrator.run()

    # regenerated once: both scripted concept rounds were consumed
    assert len(concept_adapter.calls) == 6
    # the second attempt's prompt carried the first rejection's feedback
    second_attempt_prompts = [prompt for prompt, _files in concept_adapter.calls[3:]]
    assert any("attempt feedback: reject" in p for p in second_attempt_prompts)


def test_gate_outcome_recorded_on_first_approval_lets_idempotent_resume_skip(
    tmp_path: Path,
) -> None:
    orchestrator, folder, text_adapter, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    from harness.journal import latest_gate_outcome

    outcome = latest_gate_outcome(folder, "concept")
    assert outcome is not None
    assert outcome.decision == "approve"

    calls_after_first = len(text_adapter.calls)
    orchestrator.run()
    assert len(text_adapter.calls) == calls_after_first  # concept was not regenerated


def test_editing_an_approved_artifact_forces_the_gate_to_run_again(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    # simulate a human editing the approved concept by hand afterward. This
    # also changes the frozen spec's hash, so T-330's cascade needs enough
    # scripted responses for tickets/implement to regenerate too — the point
    # under test here is only that the concept *gate* runs again, without
    # a fresh concept *generation* (apply_gate re-approves the edited text
    # directly; no adapter call is needed for concept itself).
    folder.write_text(folder.spec_concept_md, READY_CONCEPT + "\n## Extra\nedited by hand.\n")
    orchestrator.tickets_adapter = FakeTextAdapter(
        script=[GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10))]
    )
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="reimplemented", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
        ]
    )
    gate_calls: list[str] = []

    def spy_gate_io(artifact: str) -> GateResponse:
        gate_calls.append(artifact)
        return GateResponse(decision="approve")

    orchestrator.gate_io = spy_gate_io
    orchestrator.config.gates.concept = "interactive"

    orchestrator.run()

    assert gate_calls  # the gate ran again because the hash no longer matched
    assert "edited by hand" in folder.spec_concept_md.read_text(encoding="utf-8")


def test_crash_before_gate_approval_regates_the_existing_artifact_without_regenerating(
    tmp_path: Path,
) -> None:
    # the concept stage's generation completed and wrote concept.md, but the
    # process crashed before the gate outcome was recorded — no GateOutcome
    # exists yet, even though the file is already on disk.
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.spec_concept_md, READY_CONCEPT)
    folder.write_text(folder.spec_open_questions_md, NO_BLOCKING)
    folder.write_text(folder.spec_phasing_yaml, "phases: []\nstop_after_active_phase: false\n")

    config_path = tmp_path / "harness.config.yaml"
    interactive_config = CONFIG_YAML.replace("concept: auto_approve", "concept: interactive")
    config_path.write_text(interactive_config, encoding="utf-8")
    config = load_config(config_path)

    # no items scripted for concept generation — proves it is never re-run
    text_adapter = FakeTextAdapter(
        script=[
            GenerationResult(text=GUIDELINES_TEXT, usage=TokenUsage(10, 10)),
            GenerationResult(text=CONSOLIDATION_NO_CONFLICT, usage=TokenUsage(10, 10)),
            GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10)),
        ]
    )
    gate_calls: list[str] = []

    def spy_gate_io(artifact: str) -> GateResponse:
        gate_calls.append(artifact)
        return GateResponse(decision="approve")

    orchestrator = Orchestrator(
        folder=folder,
        config=config,
        clock=FrozenClock(FIXED),
        concept_adapter=text_adapter,
        guidelines_adapter=text_adapter,
        tickets_adapter=text_adapter,
        coding_adapter=FakeCodingAgent(
            script=[
                ScriptedRun(
                    result=AgentResult(
                        success=True, summary="implemented", usage=TokenUsage(1, 1), cost_usd=0.0
                    )
                ),
                ScriptedRun(
                    result=AgentResult(
                        success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                    )
                ),
            ]
        ),
        reviewer_adapter=AlwaysPassReviewer(),
        sandbox=ScriptedSandbox(root=tmp_path),
        gate_io=spy_gate_io,
        ask_user=lambda _q: "n/a",
        budget_guard=BudgetGuard(max_usd_per_run=1000, warn_at_usd=900),
    )

    orchestrator.run()

    assert gate_calls  # the gate ran on the pre-existing artifact
    # only guidelines + consolidation + tickets called the shared adapter —
    # concept generation never consumed any of its scripted items
    assert len(text_adapter.calls) == 3


def test_run_log_has_one_entry_per_text_adapter_call_with_template_identity(
    tmp_path: Path,
) -> None:
    orchestrator, folder, text_adapter, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    call_entries = [
        e for e in read_run_log(folder) if e.event is None and e.provider_or_agent == "anthropic"
    ]
    assert len(call_entries) == len(text_adapter.calls) == 6
    assert [e.prompt_template for e in call_entries] == [
        "brainstorm",
        "concept_write",
        "concept_self_review",
        "guidelines",
        "guidelines_consolidation",
        "tickets",
    ]
    assert all(e.prompt_version == "v1" for e in call_entries)
    assert all(e.wall_time_s >= 0 for e in call_entries)


def test_run_log_records_stage_3_agent_and_reviewer_calls(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    agents = [e for e in read_run_log(folder) if e.provider_or_agent == "claude-code"]
    assert {e.prompt_template for e in agents} == {"implement_bootstrap", "review_gate"}
    # one implement call for the ticket + one for the final acceptance pass,
    # plus one review_gate call for the ticket's gate
    assert len(agents) == 3


def test_run_log_records_stage_artifact_hashes_after_each_text_stage(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    artifact_entries = [e for e in read_run_log(folder) if e.event == "stage_artifacts"]
    assert {e.stage for e in artifact_entries} == {"concept", "guidelines", "tickets"}
    concept_entry = next(e for e in artifact_entries if e.stage == "concept")
    assert "spec/concept.md" in concept_entry.artifact_hashes


def test_budget_warning_crossing_emits_a_run_log_event_and_callback(tmp_path: Path) -> None:
    warn_config = CONFIG_YAML.replace(
        "max_usd_per_run: 1000\n  warn_at_usd: 900",
        "max_usd_per_run: 1000\n  warn_at_usd: 0.0000001",
    )
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path, config_text=warn_config)
    warnings: list[str] = []
    orchestrator.on_warning = warnings.append

    orchestrator.run()

    assert len(warnings) == 1
    warning_entries = [e for e in read_run_log(folder) if e.event == "budget_warning"]
    assert len(warning_entries) == 1


def test_idempotent_second_run_appends_no_further_run_log_entries(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()
    entries_after_first = len(read_run_log(folder))

    orchestrator.run()

    assert len(read_run_log(folder)) == entries_after_first


def test_freeze_happens_after_guidelines_and_is_reused_on_resume(tmp_path: Path) -> None:
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()

    from harness.freeze import latest_version

    version_after_first = latest_version(folder)
    assert version_after_first is not None

    # re-running (idempotent) must not create a second frozen version
    orchestrator.run()
    assert latest_version(folder) == version_after_first


def test_editing_concept_after_freeze_reflows_and_invalidates_downstream(tmp_path: Path) -> None:
    from harness.freeze import is_stale, latest_version, read_frozen
    from harness.journal import read_decisions

    # editing concept.md re-approves the existing (edited) text directly —
    # no fresh concept generation — but invalidates tickets, so the tickets/
    # implement fakes need a second round's worth of scripted responses.
    tickets_round: list[GenerationResult | Exception] = [
        GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10))
    ]
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()
    old_version = latest_version(folder)
    assert old_version is not None
    old_overview_hash = hashlib.sha256(
        (folder.spec_tickets_dir / "000-overview.md").read_bytes()
    ).hexdigest()

    orchestrator.tickets_adapter = FakeTextAdapter(script=tickets_round)
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="reimplemented", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
        ]
    )
    folder.write_text(folder.spec_concept_md, READY_CONCEPT + "\n## Extra\nedited by hand.\n")
    orchestrator.gate_io = lambda artifact: GateResponse(decision="approve")

    orchestrator.run()

    new_version = latest_version(folder)
    assert new_version is not None
    assert new_version != old_version
    assert is_stale(folder, old_version) is True
    assert is_stale(folder, new_version) is False
    # the old frozen snapshot itself remains untouched and readable
    assert "edited by hand" not in read_frozen(folder, old_version).concept_text

    # invalidated tickets were moved aside, not deleted
    invalidated = list(folder.spec_invalidated_dir.glob(f"{new_version}/tickets/*.md"))
    assert any(p.name == "000-overview.md" for p in invalidated)
    new_overview_hash = hashlib.sha256(
        (folder.spec_tickets_dir / "000-overview.md").read_bytes()
    ).hexdigest()
    assert new_overview_hash == old_overview_hash  # regenerated from the same script text, ok

    decisions = read_decisions(folder)
    assert any("re-froze" in d.resolution for d in decisions)


def test_unchanged_spec_across_two_runs_does_not_reinvalidate(tmp_path: Path) -> None:
    from harness.freeze import latest_version

    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()
    version_after_first = latest_version(folder)

    orchestrator.run()

    assert latest_version(folder) == version_after_first
    assert not folder.spec_invalidated_dir.exists()


def test_from_tickets_invalidates_tickets_and_regenerates_without_touching_concept(
    tmp_path: Path,
) -> None:
    from harness.freeze import latest_version

    tickets_round: list[GenerationResult | Exception] = [
        GenerationResult(text=TICKETS_RESPONSE, usage=TokenUsage(10, 10))
    ]
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.run()
    version_after_first = latest_version(folder)
    concept_before = folder.spec_concept_md.read_text(encoding="utf-8")

    orchestrator.tickets_adapter = FakeTextAdapter(script=tickets_round)
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="reimplemented", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="no drift", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            ),
        ]
    )
    orchestrator.invalidate_from("tickets")
    orchestrator.run()

    # concept/guidelines/freeze untouched: no re-freeze needed
    assert latest_version(folder) == version_after_first
    assert folder.spec_concept_md.read_text(encoding="utf-8") == concept_before
    assert (folder.spec_tickets_dir / "000-overview.md").exists()
    invalidated_ticket_dirs = list(folder.spec_invalidated_dir.glob("manual-*/tickets"))
    assert len(invalidated_ticket_dirs) == 1


def test_project_prompt_template_dir_and_version_reach_every_text_stage(tmp_path: Path) -> None:
    # a project-level override directory containing a distinctively-marked
    # v1/brainstorm.md must be used instead of the shipped default (T-400)
    override_dir = tmp_path / "custom_prompts"
    (override_dir / "v1").mkdir(parents=True)
    (override_dir / "v1" / "brainstorm.md").write_text(
        "OVERRIDE-MARKER Requirements: {{requirements}} Instructions: {{instructions}}",
        encoding="utf-8",
    )
    config_with_override = (
        CONFIG_YAML + "\nprompts:\n  template_dir: ./custom_prompts\n  version: v1\n"
    )
    orchestrator, _folder, text_adapter, _coding = setup_orchestrator(
        tmp_path, config_text=config_with_override
    )

    orchestrator.run()

    brainstorm_prompt = text_adapter.calls[0][0]
    assert "OVERRIDE-MARKER" in brainstorm_prompt


def test_require_tests_green_and_require_llm_review_flags_reach_the_review_gate(
    tmp_path: Path,
) -> None:
    config_relaxed = (
        CONFIG_YAML + "\nimplementation:\n  review:\n    require_tests_green: false\n"
        "    require_llm_review: false\n"
    )
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path, config_text=config_relaxed)
    reviewer = AlwaysPassReviewer()
    orchestrator.reviewer_adapter = reviewer

    orchestrator.run()

    # per-ticket review is skipped (require_llm_review is false); the final
    # acceptance pass (T-410) is a distinct read-only check against the
    # original requirements and always runs regardless of that flag
    assert reviewer.calls == 1
    from harness.journal import read_decisions

    decisions = read_decisions(folder)
    assert any("both false" in d.conflict or "are both false" in d.conflict for d in decisions)


def test_agent_reported_cost_counts_against_the_same_budget_ledger_as_text_stages(
    tmp_path: Path,
) -> None:
    # T-510: Stage 3's self-reported agent cost must halt the run just like
    # a text-stage overspend does — it was previously tracked in run.log
    # only, entirely outside the budget cap.
    modest_config = CONFIG_YAML.replace(
        "max_usd_per_run: 1000\n  warn_at_usd: 900", "max_usd_per_run: 2.0\n  warn_at_usd: 1.9"
    )
    orchestrator, folder, _text, _coding = setup_orchestrator(tmp_path, config_text=modest_config)
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="expensive", usage=TokenUsage(1, 1), cost_usd=5.0
                )
            )
        ]
    )

    with pytest.raises(BudgetExceeded):
        orchestrator.run()

    # the ticket never completed (the cost that broke the cap was its own) —
    # no progress entry was recorded for it, and a later run (with a raised
    # cap) would resume from scratch on this ticket, not silently skip it
    assert read_progress(folder) == []


def test_agent_cost_accumulates_with_text_stage_cost_in_one_total(tmp_path: Path) -> None:
    orchestrator, _folder, _text, _coding = setup_orchestrator(tmp_path)
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="implemented", usage=TokenUsage(1, 1), cost_usd=3.0
                )
            )
        ]
    )

    orchestrator.run()

    # the agent's $3.00 plus whatever the (tiny) text-stage calls cost
    assert orchestrator.budget_guard.total_spent_usd >= 3.0


def test_retry_exhaustion_halts_cleanly_instead_of_raising_a_traceback(tmp_path: Path) -> None:
    from harness.adapters.claude_code import ReviewResult
    from harness.journal import latest_escalation_for

    class AlwaysFailReviewer:
        def review(
            self,
            ticket: str,
            diff_paths: list[Path],
            criteria: str,
            objective_results: str,
            prompt: str,
        ) -> ReviewResult:
            return ReviewResult(passed=False, reasons=["never good enough"], usage=TokenUsage(0, 0))

    tight_retry_config = CONFIG_YAML + "\nimplementation:\n  retry_budget: 0\n"
    orchestrator, folder, _text, _coding = setup_orchestrator(
        tmp_path, config_text=tight_retry_config
    )
    orchestrator.coding_adapter = FakeCodingAgent(
        script=[
            ScriptedRun(
                result=AgentResult(
                    success=True, summary="tried", usage=TokenUsage(1, 1), cost_usd=0.0
                )
            )
        ]
    )
    orchestrator.reviewer_adapter = AlwaysFailReviewer()

    result = orchestrator.run()

    assert result.halted is True
    assert result.halt_reason == "escalation"
    assert result.warnings
    assert "T-010" in result.warnings[0]

    escalation = latest_escalation_for(folder, "T-010")
    assert escalation is not None
    assert escalation.kind == "retry_exhausted"
