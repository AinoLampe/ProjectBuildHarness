"""ClaudeCodeAdapter.run() must pass the shared CodingAgentAdapter contract
(T-140), exercised against an injected process runner — no real `claude`
process is spawned."""

import json
import subprocess
from pathlib import Path

import pytest

from harness.adapters.claude_code import ClaudeCodeAdapter
from harness.adapters.coding import CodingAgentAdapter
from harness.core.errors import AdapterError
from harness.sandbox import Sandbox
from tests.contract.coding_contract import CodingAgentContract


def _completed(stdout: str, returncode: int = 0) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


class TestClaudeCodeAdapterContract(CodingAgentContract):
    def make_adapter(self) -> CodingAgentAdapter:
        # the real `claude -p --output-format json` envelope shape (T-340)
        payload = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "did the thing",
                "total_cost_usd": 0.05,
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )

        def fake_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
            return _completed(payload)

        return ClaudeCodeAdapter(
            project_root=Path("."),
            implement_model="claude-sonnet-4-6",
            review_model="claude-opus-4-8",
            process_runner=fake_runner,
        )

    def make_failing_adapter(self) -> CodingAgentAdapter:
        def failing_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
            raise OSError("claude binary not found")

        return ClaudeCodeAdapter(
            project_root=Path("."),
            implement_model="claude-sonnet-4-6",
            review_model="claude-opus-4-8",
            process_runner=failing_runner,
        )


def _adapter_with_stdout(stdout: str) -> ClaudeCodeAdapter:
    def fake_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        return _completed(stdout)

    return ClaudeCodeAdapter(
        project_root=Path("."),
        implement_model="claude-sonnet-4-6",
        review_model="claude-opus-4-8",
        process_runner=fake_runner,
    )


def test_run_extracts_usage_and_cost_from_the_real_envelope_shape(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "done",
            "total_cost_usd": 0.1234,
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }
    )
    adapter = _adapter_with_stdout(payload)
    result = adapter.run(tmp_path, "prompt", Sandbox(root=tmp_path))

    assert result.success is True
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 200
    assert result.cost_usd == 0.1234


def test_run_reports_failure_when_the_envelope_marks_is_error(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "result": "something went wrong",
            "total_cost_usd": 0.01,
            "usage": {"input_tokens": 5, "output_tokens": 1},
        }
    )
    adapter = _adapter_with_stdout(payload)
    result = adapter.run(tmp_path, "prompt", Sandbox(root=tmp_path))

    assert result.success is False
    assert result.summary == "something went wrong"


def test_run_command_includes_a_bash_deny_list(tmp_path: Path) -> None:
    recorded: list[list[str]] = []

    def recording_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        recorded.append(command)
        return _completed(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "ok",
                    "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            )
        )

    adapter = ClaudeCodeAdapter(
        project_root=tmp_path,
        implement_model="claude-sonnet-4-6",
        review_model="claude-opus-4-8",
        process_runner=recording_runner,
    )
    adapter.run(tmp_path, "prompt", Sandbox(root=tmp_path))

    command = recorded[0]
    assert "--disallowedTools" in command
    deny_list = command[command.index("--disallowedTools") + 1]
    assert "rm -rf /" in deny_list


def test_invoke_wraps_a_timeout_as_adapter_error(tmp_path: Path) -> None:
    def timing_out_runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        raise subprocess.TimeoutExpired(cmd=command, timeout=1800.0)

    adapter = ClaudeCodeAdapter(
        project_root=tmp_path,
        implement_model="claude-sonnet-4-6",
        review_model="claude-opus-4-8",
        process_runner=timing_out_runner,
    )
    with pytest.raises(AdapterError, match="timed out"):
        adapter.run(tmp_path, "prompt", Sandbox(root=tmp_path))


def test_default_process_runner_honours_command_timeout_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def _capture(*_args: object, **kwargs: object) -> "subprocess.CompletedProcess[str]":
        captured["timeout"] = kwargs.get("timeout")
        return _completed(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "ok",
                    "total_cost_usd": 0.0,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            )
        )

    monkeypatch.setattr("harness.adapters.claude_code.subprocess.run", _capture)
    adapter = ClaudeCodeAdapter(
        project_root=tmp_path,
        implement_model="claude-sonnet-4-6",
        review_model="claude-opus-4-8",
        command_timeout_s=42.0,
    )
    adapter.run(tmp_path, "prompt", Sandbox(root=tmp_path))
    assert captured["timeout"] == 42.0
