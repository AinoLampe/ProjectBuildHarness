"""Behavioural tests for `ClaudeCodeAdapter.review()` (T-140, T-340): fresh
session, read-only tools, the configured review model, and a structured
verdict — exercised against an injected process runner, no real `claude`
process.

The verdict JSON lives *inside* the real CLI envelope's `result` text, not
at the envelope's top level (T-340) — `make_adapter_recording_commands`
builds that real envelope shape around each scripted verdict."""

import json
import subprocess
from pathlib import Path

from harness.adapters.claude_code import ClaudeCodeAdapter


def _envelope(result_text: str, *, input_tokens: int = 5, output_tokens: int = 7) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result_text,
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


def make_adapter_recording_commands(
    stdout: str,
) -> tuple[ClaudeCodeAdapter, list[list[str]]]:
    recorded: list[list[str]] = []

    def recording_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        recorded.append(command)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    adapter = ClaudeCodeAdapter(
        project_root=Path("/project"),
        implement_model="claude-sonnet-4-6",
        review_model="claude-opus-4-8",
        process_runner=recording_runner,
    )
    return adapter, recorded


def test_review_uses_a_fresh_session_with_no_resume_or_continue_flags() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": []}))
    adapter, recorded = make_adapter_recording_commands(stdout)
    adapter.review("T-080", [], "criteria", "tests green", "orchestrator-built prompt")

    command = recorded[0]
    assert "--resume" not in command
    assert "--continue" not in command


def test_review_uses_read_only_tools_only() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": []}))
    adapter, recorded = make_adapter_recording_commands(stdout)
    adapter.review("T-080", [], "criteria", "tests green", "prompt")

    command = recorded[0]
    tools = command[command.index("--allowedTools") + 1]
    assert set(tools.split(",")) == {"Read", "Glob", "Grep"}
    assert "Write" not in tools
    assert "Edit" not in tools
    assert "Bash" not in tools


def test_review_uses_the_configured_review_model() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": []}))
    adapter, recorded = make_adapter_recording_commands(stdout)
    adapter.review("T-080", [], "criteria", "tests green", "prompt")

    command = recorded[0]
    assert command[command.index("--model") + 1] == "claude-opus-4-8"


def test_review_sends_exactly_the_orchestrator_supplied_prompt() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": []}))
    adapter, recorded = make_adapter_recording_commands(stdout)
    adapter.review("T-080", [], "criteria", "tests green", "the exact orchestrator prompt")

    command = recorded[0]
    assert command[command.index("-p") + 1] == "the exact orchestrator prompt"


def test_review_returns_passing_structured_verdict() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": ["looks good"]}))
    adapter, _recorded = make_adapter_recording_commands(stdout)
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.passed is True
    assert result.reasons == ["looks good"]


def test_review_returns_failing_structured_verdict() -> None:
    stdout = _envelope(json.dumps({"pass": False, "reasons": ["missing edge case test"]}))
    adapter, _recorded = make_adapter_recording_commands(stdout)
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.passed is False
    assert result.reasons == ["missing edge case test"]


def test_review_extracts_usage_from_the_envelope() -> None:
    stdout = _envelope(json.dumps({"pass": True, "reasons": []}), input_tokens=42, output_tokens=99)
    adapter, _recorded = make_adapter_recording_commands(stdout)
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.usage.input_tokens == 42
    assert result.usage.output_tokens == 99


def test_verdict_embedded_in_surrounding_prose_or_fencing_is_still_parsed() -> None:
    stdout = _envelope(
        'Here is my assessment:\n```json\n{"pass": true, "reasons": ["fine"]}\n```\nDone.'
    )
    adapter, _recorded = make_adapter_recording_commands(stdout)
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.passed is True
    assert result.reasons == ["fine"]


def test_unparseable_top_level_stdout_is_a_failed_review_not_an_exception() -> None:
    adapter, _recorded = make_adapter_recording_commands("not json at all")
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.passed is False
    assert result.reasons != []


def test_unparseable_verdict_inside_a_valid_envelope_is_a_failed_review() -> None:
    stdout = _envelope("I looked at it and it seems okay, no structured verdict here.")
    adapter, _recorded = make_adapter_recording_commands(stdout)
    result = adapter.review("T-080", [], "criteria", "tests green", "prompt")
    assert result.passed is False
    assert result.reasons != []
