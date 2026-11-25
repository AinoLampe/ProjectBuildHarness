"""Gated smoke tests: real `claude -p` invocations. Skipped unless the
`claude` CLI is on PATH (guidelines §4.2 — real adapters smoke-tested
separately from the contract suite)."""

import shutil
from pathlib import Path

import pytest

from harness.adapters.claude_code import ClaudeCodeAdapter
from harness.sandbox import Sandbox

pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None, reason="requires the claude CLI on PATH for a live smoke test"
)


def test_real_run_in_a_temporary_project_produces_a_file_change(tmp_path: Path) -> None:
    adapter = ClaudeCodeAdapter(
        project_root=tmp_path, implement_model="claude-sonnet-4-6", review_model="claude-opus-4-8"
    )
    sandbox = Sandbox(root=tmp_path)
    result = adapter.run(tmp_path, "Create a file named hello.txt containing 'hi'.", sandbox)
    assert result.success is True
    assert (tmp_path / "hello.txt").exists()


def test_real_review_on_a_real_file_returns_a_parseable_verdict(tmp_path: Path) -> None:
    # a trivially compliant case with a known expected outcome — a bool-typed
    # result alone wouldn't catch a reviewer that always says "unparseable"
    # (T-340: the old assertion here was vacuous against the invented envelope
    # schema that predated the real CLI's actual output shape).
    target = tmp_path / "hello.txt"
    target.write_text("hi", encoding="utf-8")
    adapter = ClaudeCodeAdapter(
        project_root=tmp_path, implement_model="claude-sonnet-4-6", review_model="claude-opus-4-8"
    )
    result = adapter.review(
        ticket="T-SMOKE",
        diff_paths=[target],
        criteria="the file hello.txt exists and contains 'hi'",
        objective_results="tests green",
        prompt=(
            'Check that hello.txt exists and contains "hi". '
            'Respond with exactly one JSON object: {"pass": bool, "reasons": [string]}.'
        ),
    )
    assert result.passed is True
    assert result.reasons == [] or all(isinstance(r, str) for r in result.reasons)
