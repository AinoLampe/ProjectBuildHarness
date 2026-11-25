"""Test-first behavioural tests for the per-ticket review gate (T-200), with
fakes for the adapter and sandbox."""

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from harness.adapters.claude_code import ReviewResult
from harness.adapters.text import TokenUsage
from harness.sandbox import CommandResult
from harness.stages.review import GateResult, run_review_gate


class FakeSandbox:
    def __init__(self, *, exit_codes: dict[str, int] | None = None) -> None:
        self._exit_codes = exit_codes or {}
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> CommandResult:
        self.commands.append(command)
        tool = command[0]
        exit_code = self._exit_codes.get(tool, 0)
        return CommandResult(exit_code=exit_code, stdout=f"{tool} output", stderr="")


class FakeReviewerAdapter:
    def __init__(self, *, verdict: ReviewResult) -> None:
        self._verdict = verdict
        self.review_calls: list[tuple[str, list[Path], str, str, str]] = []
        self.run_was_called = False

    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewResult:
        self.review_calls.append((ticket, diff_paths, criteria, objective_results, prompt))
        return self._verdict

    def run(self, *args: object, **kwargs: object) -> None:
        self.run_was_called = True
        raise AssertionError("the review gate must never call adapter.run()")


def run(coro: Coroutine[Any, Any, GateResult]) -> GateResult:
    return asyncio.run(coro)


def test_automated_checks_failing_means_reviewer_is_never_called() -> None:
    sandbox = FakeSandbox(exit_codes={"pytest": 1})
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=["tests/unit/test_dag.py"],
            changed_paths=[Path("src/harness/dag.py")],
            sandbox=sandbox,
            adapter=adapter,
        )
    )

    assert result.passed is False
    assert adapter.review_calls == []
    assert "automated" in " ".join(result.reasons).lower()


def test_automated_checks_pass_and_reviewer_passes_means_gate_passes() -> None:
    sandbox = FakeSandbox()
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=True, reasons=["looks good"], usage=TokenUsage(1, 1))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=["tests/unit/test_dag.py"],
            changed_paths=[Path("src/harness/dag.py")],
            sandbox=sandbox,
            adapter=adapter,
        )
    )

    assert result.passed is True
    assert result.objective.all_passed is True
    assert len(adapter.review_calls) == 1


def test_automated_checks_pass_and_reviewer_rejects_means_gate_fails() -> None:
    sandbox = FakeSandbox()
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=False, reasons=["missing edge case"], usage=TokenUsage(1, 1))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=["tests/unit/test_dag.py"],
            changed_paths=[Path("src/harness/dag.py")],
            sandbox=sandbox,
            adapter=adapter,
        )
    )

    assert result.passed is False
    assert result.reasons == ["missing edge case"]


def test_reviewer_receives_orchestrator_assembled_prompt_not_implementer_text() -> None:
    sandbox = FakeSandbox()
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))
    )

    run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.\n## Acceptance criteria\n- works",
            test_paths=["tests/unit/test_dag.py"],
            changed_paths=[Path("src/harness/dag.py")],
            sandbox=sandbox,
            adapter=adapter,
        )
    )

    _ticket, diff_paths, _criteria, objective_results, prompt = adapter.review_calls[0]
    assert diff_paths == [Path("src/harness/dag.py")]
    assert "Goal" in prompt
    assert "Acceptance criteria" in prompt
    assert "pytest output" in objective_results
    assert not adapter.run_was_called


def test_unparseable_or_failed_reviewer_is_a_failed_gate_not_an_exception() -> None:
    sandbox = FakeSandbox()
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=False, reasons=["unparseable response"], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=[],
            changed_paths=[],
            sandbox=sandbox,
            adapter=adapter,
        )
    )
    assert result.passed is False


def test_run_review_gate_is_gatherable_concurrently() -> None:
    async def two_at_once() -> tuple[GateResult, GateResult]:
        sandbox_a = FakeSandbox()
        sandbox_b = FakeSandbox()
        adapter_a = FakeReviewerAdapter(
            verdict=ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))
        )
        adapter_b = FakeReviewerAdapter(
            verdict=ReviewResult(passed=False, reasons=["no"], usage=TokenUsage(0, 0))
        )
        return await asyncio.gather(
            run_review_gate(
                ticket_id="T-001",
                ticket_text="t1",
                test_paths=[],
                changed_paths=[],
                sandbox=sandbox_a,
                adapter=adapter_a,
            ),
            run_review_gate(
                ticket_id="T-002",
                ticket_text="t2",
                test_paths=[],
                changed_paths=[],
                sandbox=sandbox_b,
                adapter=adapter_b,
            ),
        )

    result_a, result_b = asyncio.run(two_at_once())
    assert result_a.passed is True
    assert result_b.passed is False


def test_require_tests_green_false_skips_objective_checks_but_still_calls_reviewer() -> None:
    sandbox = FakeSandbox(exit_codes={"pytest": 1})  # would fail if checked
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=[],
            changed_paths=[],
            sandbox=sandbox,
            adapter=adapter,
            require_tests_green=False,
        )
    )

    assert sandbox.commands == []  # never ran any automated check
    assert len(adapter.review_calls) == 1
    assert result.passed is True


def test_require_llm_review_false_skips_the_reviewer_when_tests_pass() -> None:
    sandbox = FakeSandbox()
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=False, reasons=["would have failed"], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=[],
            changed_paths=[],
            sandbox=sandbox,
            adapter=adapter,
            require_llm_review=False,
        )
    )

    assert adapter.review_calls == []
    assert result.passed is True


def test_require_llm_review_false_still_fails_if_tests_fail() -> None:
    sandbox = FakeSandbox(exit_codes={"pytest": 1})
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=True, reasons=[], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=[],
            changed_paths=[],
            sandbox=sandbox,
            adapter=adapter,
            require_llm_review=False,
        )
    )

    assert adapter.review_calls == []
    assert result.passed is False


def test_both_review_requirements_false_passes_trivially_with_no_verification() -> None:
    sandbox = FakeSandbox(exit_codes={"pytest": 1})
    adapter = FakeReviewerAdapter(
        verdict=ReviewResult(passed=False, reasons=["would have failed"], usage=TokenUsage(0, 0))
    )

    result = run(
        run_review_gate(
            ticket_id="T-080",
            ticket_text="## Goal\nDo the thing.",
            test_paths=[],
            changed_paths=[],
            sandbox=sandbox,
            adapter=adapter,
            require_tests_green=False,
            require_llm_review=False,
        )
    )

    assert sandbox.commands == []
    assert adapter.review_calls == []
    assert result.passed is True
