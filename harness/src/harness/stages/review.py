"""Per-ticket review gate (concept §10.3): a ticket is complete only when
automated checks are green **and** an independent, fresh-session LLM
reviewer confirms it. Driven by the orchestrator — the implementer never
calls this, and never assembles the reviewer's prompt (principle §1.7).

`run_review_gate` is `async` so v0 can `await` it sequentially and v2 can
`asyncio.gather()` independent tickets without any refactor. The reviewer
adapter (`ClaudeCodeAdapter.review`, T-140) is itself synchronous; see
DECISIONS.md (T-200) for why this function awaits it via
`asyncio.to_thread` rather than retrofitting T-140.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from harness.prompts import DEFAULT_TEMPLATE_VERSION, render_prompt
from harness.sandbox import CommandResult

_ACCEPTANCE_CRITERIA_RE = re.compile(
    r"##\s*Acceptance criteria\s*\n(.*?)(?=\n##\s|\Z)", re.IGNORECASE | re.DOTALL
)


def _extract_acceptance_criteria(ticket_text: str) -> str:
    """Pull just the '## Acceptance criteria' section out of the ticket, so
    the reviewer prompt can highlight the objective pass/fail bar
    separately from the ticket's full context (T-550)."""
    match = _ACCEPTANCE_CRITERIA_RE.search(ticket_text)
    return match.group(1).strip() if match else "(no explicit Acceptance criteria section found)"


class SandboxLike(Protocol):
    def run(self, command: list[str]) -> CommandResult: ...


class ReviewerVerdictLike(Protocol):
    @property
    def passed(self) -> bool: ...

    @property
    def reasons(self) -> list[str]: ...


class ReviewerAdapter(Protocol):
    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewerVerdictLike: ...


@dataclass(frozen=True)
class ObjectiveResult:
    tests_passed: bool
    lint_passed: bool
    format_passed: bool
    types_passed: bool
    output: str

    @property
    def all_passed(self) -> bool:
        return self.tests_passed and self.lint_passed and self.format_passed and self.types_passed


@dataclass(frozen=True)
class GateResult:
    passed: bool
    objective: ObjectiveResult
    llm_verdict: ReviewerVerdictLike | None
    reasons: list[str]


def run_objective_checks(sandbox: SandboxLike, test_paths: list[str]) -> ObjectiveResult:
    test_command = ["pytest", *test_paths] if test_paths else ["pytest"]
    test_result = sandbox.run(test_command)
    lint_result = sandbox.run(["ruff", "check", "."])
    format_result = sandbox.run(["ruff", "format", "--check", "."])
    types_result = sandbox.run(["pyright"])

    output = "\n".join(
        f"$ {' '.join(cmd)}\n{result.stdout}{result.stderr}"
        for cmd, result in (
            (test_command, test_result),
            (["ruff", "check", "."], lint_result),
            (["ruff", "format", "--check", "."], format_result),
            (["pyright"], types_result),
        )
    )

    return ObjectiveResult(
        tests_passed=test_result.exit_code == 0,
        lint_passed=lint_result.exit_code == 0,
        format_passed=format_result.exit_code == 0,
        types_passed=types_result.exit_code == 0,
        output=output,
    )


_SKIPPED_OBJECTIVE = ObjectiveResult(
    tests_passed=True,
    lint_passed=True,
    format_passed=True,
    types_passed=True,
    output="(automated checks skipped: implementation.review.require_tests_green=false)",
)


async def run_review_gate(
    *,
    ticket_id: str,
    ticket_text: str,
    test_paths: list[str],
    changed_paths: list[Path],
    sandbox: SandboxLike,
    adapter: ReviewerAdapter,
    prompt_version: str = DEFAULT_TEMPLATE_VERSION,
    template_dir: Path | None = None,
    require_tests_green: bool = True,
    require_llm_review: bool = True,
    concept_path: str = "",
    guidelines_path: str = "",
) -> GateResult:
    """`require_tests_green`/`require_llm_review` (T-400) let a project
    configure the gate down to just one signal — the harness still
    considers both "on" the trustworthy default and never enables either
    from within this function; the caller decides and is responsible for
    surfacing it if both end up `False` (a ticket that ships with no
    verification at all)."""
    if require_tests_green:
        objective = run_objective_checks(sandbox, test_paths)
        if not objective.all_passed:
            return GateResult(
                passed=False,
                objective=objective,
                llm_verdict=None,
                reasons=["automated checks (tests/lint/format/types) failed; reviewer not invoked"],
            )
    else:
        objective = _SKIPPED_OBJECTIVE

    if not require_llm_review:
        return GateResult(
            passed=True,
            objective=objective,
            llm_verdict=None,
            reasons=["LLM review skipped: implementation.review.require_llm_review=false"],
        )

    prompt = render_prompt(
        "review_gate",
        prompt_version,
        {
            "ticket_text": ticket_text,
            "acceptance_criteria": _extract_acceptance_criteria(ticket_text),
            "changed_files": "\n".join(str(p) for p in changed_paths),
            "objective_results": objective.output,
            "concept_path": concept_path,
            "guidelines_path": guidelines_path,
        },
        template_dir=template_dir,
    )

    verdict = await asyncio.to_thread(
        adapter.review, ticket_id, changed_paths, ticket_text, objective.output, prompt
    )

    return GateResult(
        passed=verdict.passed, objective=objective, llm_verdict=verdict, reasons=verdict.reasons
    )
