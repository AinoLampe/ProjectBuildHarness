"""Fake-driven end-to-end tests for Stage 3 (T-210)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.adapters.claude_code import ReviewResult
from harness.adapters.coding import AgentResult
from harness.adapters.text import TokenUsage
from harness.core.clock import FrozenClock
from harness.core.errors import EscalationRequired, StageError
from harness.folder import ProjectFolder
from harness.freeze import freeze_spec
from harness.journal import ProgressEntry, latest_escalation_for, record_progress
from harness.sandbox import CommandResult, Sandbox
from harness.stages.implement import ImplementStage
from tests.fakes.fake_coding import FakeCodingAgent, ScriptedRun

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


class ScriptedSandbox(Sandbox):
    def __init__(self, root: Path, exit_codes: dict[str, int] | None = None) -> None:
        super().__init__(root=root)
        self._exit_codes = exit_codes or {}

    def run(self, command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        tool = command[0]
        exit_code = self._exit_codes.get(tool, 0)
        return CommandResult(exit_code=exit_code, stdout=f"{tool} ok", stderr="")


class FakeReviewerAdapter:
    def __init__(self, verdicts: list[ReviewResult]) -> None:
        self._verdicts = list(verdicts)
        self._index = 0
        self.calls: list[str] = []
        self.diff_paths_calls: list[list[Path]] = []
        self.objective_results_calls: list[str] = []

    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewResult:
        self.calls.append(ticket)
        self.diff_paths_calls.append(diff_paths)
        self.objective_results_calls.append(objective_results)
        verdict = self._verdicts[min(self._index, len(self._verdicts) - 1)]
        self._index += 1
        return verdict


class RecordingSandbox(Sandbox):
    def __init__(self, root: Path) -> None:
        super().__init__(root=root)
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        self.commands.append(command)
        return CommandResult(exit_code=0, stdout="ok", stderr="")


def make_agent_result(summary: str = "did it") -> AgentResult:
    return AgentResult(success=True, summary=summary, usage=TokenUsage(1, 1), cost_usd=0.0)


def setup_project(tmp_path: Path) -> tuple[ProjectFolder, str]:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.spec_concept_md, "# Concept")
    folder.write_text(folder.spec_guidelines_md, "# Guidelines")
    frozen = freeze_spec(folder, FrozenClock(FIXED))
    folder.write_text(
        folder.spec_tickets_dir / "010-scaffolding.md",
        "# T-010\n\n## Connections\n- depends on:\n- blocks: 020\n",
    )
    folder.write_text(
        folder.spec_tickets_dir / "020-core.md",
        "# T-020\n\n## Connections\n- depends on: 010\n",
    )
    return folder, frozen.version


def make_stage(folder: ProjectFolder, version: str, *, retry_budget: int = 2) -> ImplementStage:
    return ImplementStage(
        folder=folder,
        frozen_version=version,
        clock=FrozenClock(FIXED),
        sandbox=ScriptedSandbox(folder.root),
        reviewer=FakeReviewerAdapter(verdicts=[]),
        retry_budget=retry_budget,
    )


def test_tickets_run_in_build_order(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    coding_agent = FakeCodingAgent(
        script=[ScriptedRun(result=make_agent_result()) for _ in range(3)]  # 2 tickets + final pass
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = make_stage(folder, version)
    stage.reviewer = reviewer

    stage.run(folder, coding_agent, rendered_prompt="")

    prompts = [prompt for _workdir, prompt in coding_agent.calls]
    assert prompts[0].count("T-010") >= 1
    assert prompts[1].count("T-020") >= 1


def test_retry_then_success(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    coding_agent = FakeCodingAgent(
        script=[ScriptedRun(result=make_agent_result()) for _ in range(4)]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[
            ReviewResult(passed=False, reasons=["fix it"], usage=TokenUsage(0, 0)),
            ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0)),
        ]
    )
    stage = make_stage(folder, version, retry_budget=2)
    stage.reviewer = reviewer

    stage.run(folder, coding_agent, rendered_prompt="")

    # ticket T-010 took 2 attempts before passing
    assert reviewer.calls.count("T-010") == 2


def test_retry_budget_exhaustion_escalates_and_stops(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    coding_agent = FakeCodingAgent(
        script=[ScriptedRun(result=make_agent_result()) for _ in range(5)]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=False, reasons=["always fails"], usage=TokenUsage(0, 0))]
    )
    stage = make_stage(folder, version, retry_budget=1)
    stage.reviewer = reviewer

    with pytest.raises(EscalationRequired):
        stage.run(folder, coding_agent, rendered_prompt="")

    # only T-010 was attempted (2 = retry_budget+1 attempts); T-020 never reached
    assert reviewer.calls == ["T-010", "T-010"]

    escalation = latest_escalation_for(folder, "T-010")
    assert escalation is not None
    assert escalation.kind == "retry_exhausted"
    assert escalation.resolution is None
    assert "always fails" in escalation.context


def test_crash_and_resume_skips_completed_tickets(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-010", summary="already done"))

    # only T-020 needs implementing; the final acceptance pass (T-410) goes
    # through the read-only reviewer, not adapter.run()
    coding_agent = FakeCodingAgent(script=[ScriptedRun(result=make_agent_result())])
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = make_stage(folder, version)
    stage.reviewer = reviewer

    stage.run(folder, coding_agent, rendered_prompt="")

    assert len(coding_agent.calls) == 1  # only T-020's implementation
    assert reviewer.calls == ["T-020", "__final_acceptance__"]


def test_final_acceptance_pass_surfaces_drift(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    # T-410: the final acceptance pass goes through the read-only reviewer,
    # not adapter.run() — only the two tickets need implementing.
    coding_agent = FakeCodingAgent(
        script=[
            ScriptedRun(result=make_agent_result()),
            ScriptedRun(result=make_agent_result()),
        ]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[
            ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0)),  # T-010's gate
            ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0)),  # T-020's gate
            ReviewResult(
                passed=False,
                reasons=["missing a required endpoint"],
                usage=TokenUsage(0, 0),
            ),  # final acceptance
        ]
    )
    stage = make_stage(folder, version)
    stage.reviewer = reviewer

    result = stage.run(folder, coding_agent, rendered_prompt="")

    assert result.blocking_questions
    assert "drift" in result.blocking_questions[0].lower()
    assert "missing a required endpoint" in result.blocking_questions[0]


def test_stale_frozen_version_is_rejected(tmp_path: Path) -> None:
    folder, old_version = setup_project(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v2")
    freeze_spec(folder, FrozenClock(FIXED.replace(minute=5)))

    stage = make_stage(folder, old_version)
    coding_agent = FakeCodingAgent(script=[])

    with pytest.raises(StageError, match="superseded"):
        stage.run(folder, coding_agent, rendered_prompt="")


def test_reviewer_receives_the_real_changed_files_not_a_static_src_dir(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    coding_agent = FakeCodingAgent(
        script=[
            ScriptedRun(result=make_agent_result(), writes={"src/module_a.py": "code a"}),
            ScriptedRun(result=make_agent_result(), writes={"src/module_b.py": "code b"}),
        ]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = make_stage(folder, version)
    stage.reviewer = reviewer

    stage.run(folder, coding_agent, rendered_prompt="")

    # T-010's gate saw only module_a.py, not "everything in src/" (T-520)
    t010_paths = reviewer.diff_paths_calls[0]
    assert folder.src_dir / "module_a.py" in t010_paths
    assert folder.src_dir / "module_b.py" not in t010_paths

    t020_paths = reviewer.diff_paths_calls[1]
    assert folder.src_dir / "module_b.py" in t020_paths
    assert folder.src_dir / "module_a.py" not in t020_paths


def test_declared_test_scope_runs_pytest_scoped_not_the_whole_suite(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build a thing")
    folder.write_text(folder.spec_concept_md, "# Concept")
    folder.write_text(folder.spec_guidelines_md, "# Guidelines")
    frozen = freeze_spec(folder, FrozenClock(FIXED))
    folder.write_text(
        folder.spec_tickets_dir / "010-scaffolding.md",
        "# T-010\n\n## Connections\n- depends on:\n\n### Tests\n- tests/unit/test_dag.py\n",
    )
    sandbox = RecordingSandbox(folder.root)
    coding_agent = FakeCodingAgent(script=[ScriptedRun(result=make_agent_result())])
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = ImplementStage(
        folder=folder,
        frozen_version=frozen.version,
        clock=FrozenClock(FIXED),
        sandbox=sandbox,
        reviewer=reviewer,
    )

    stage.run(folder, coding_agent, rendered_prompt="")

    pytest_commands = [cmd for cmd in sandbox.commands if cmd[0] == "pytest"]
    # one scoped run for T-010's own gate, one full run at the end (T-520)
    assert ["pytest", "tests/unit/test_dag.py"] in pytest_commands
    assert ["pytest"] in pytest_commands


def test_final_full_suite_failure_after_all_gates_pass_raises(tmp_path: Path) -> None:
    folder, version = setup_project(tmp_path)
    sandbox = ScriptedSandbox(folder.root)
    coding_agent = FakeCodingAgent(
        script=[ScriptedRun(result=make_agent_result()), ScriptedRun(result=make_agent_result())]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = ImplementStage(
        folder=folder,
        frozen_version=version,
        clock=FrozenClock(FIXED),
        sandbox=sandbox,
        reviewer=reviewer,
    )
    # simulate the full-suite pytest run failing even though every ticket's
    # own (scoped-or-full, per its declared Tests section) gate passed.
    # Neither T-010 nor T-020 declares a ### Tests section, so both their
    # own gates already fall back to a bare "pytest" (full-suite) call —
    # only the *third* bare-pytest call (the T-520 final regression check)
    # should be made to fail.
    bare_pytest_calls = {"n": 0}
    original_run = sandbox.run

    def flaky_run(command: list[str], *, timeout_s: float | None = None) -> CommandResult:
        if command == ["pytest"]:
            bare_pytest_calls["n"] += 1
            if bare_pytest_calls["n"] > 2:
                return CommandResult(exit_code=1, stdout="", stderr="regression!")
        return original_run(command, timeout_s=timeout_s)

    sandbox.run = flaky_run  # type: ignore[method-assign]

    with pytest.raises(StageError, match="final full-suite"):
        stage.run(folder, coding_agent, rendered_prompt="")


def test_a_ticket_with_an_open_escalation_is_never_re_attempted(tmp_path: Path) -> None:
    from harness.journal import EscalationRecord, record_escalation

    folder, version = setup_project(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED,
            kind="retry_exhausted",
            ticket="T-010",
            context="failed the review gate after 2 attempt(s)",
        ),
    )
    # no script at all — if the stage tried to re-run T-010 this would raise
    # AdapterError("script exhausted") instead of EscalationRequired
    coding_agent = FakeCodingAgent(script=[])
    stage = make_stage(folder, version)

    with pytest.raises(EscalationRequired, match="open escalation"):
        stage.run(folder, coding_agent, rendered_prompt="")

    assert coding_agent.calls == []


def test_resolving_an_escalation_injects_the_answer_and_gets_a_fresh_retry_budget(
    tmp_path: Path,
) -> None:
    from harness.journal import EscalationRecord, record_escalation, resolve_escalation

    folder, version = setup_project(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED,
            kind="retry_exhausted",
            ticket="T-010",
            context="failed the review gate after 2 attempt(s)",
        ),
    )
    resolve_escalation(folder, "T-010", "use library X instead", FIXED)

    coding_agent = FakeCodingAgent(
        script=[ScriptedRun(result=make_agent_result()) for _ in range(3)]
    )
    reviewer = FakeReviewerAdapter(
        verdicts=[ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))]
    )
    stage = make_stage(folder, version, retry_budget=1)
    stage.reviewer = reviewer

    stage.run(folder, coding_agent, rendered_prompt="")

    # T-010 got a fresh attempt (not immediately blocked) with the human's
    # answer folded into its bootstrap prompt
    first_ticket_prompt = coding_agent.calls[0][1]
    assert "use library X instead" in first_ticket_prompt
