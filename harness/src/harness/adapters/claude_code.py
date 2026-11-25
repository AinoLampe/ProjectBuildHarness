"""The v0 `CodingAgentAdapter` implementation: Claude Code run headlessly via
`claude -p` (concept §10, §13). A single adapter exposes two entry points
distinguished only by their arguments:

- `run()` — the implementer path: read/write tools, `config.models.implement`.
- `review()` — the reviewer path: a brand-new `claude -p` process (no
  `--resume`/`--continue`), read-only tools, `config.models.review`, fed only
  the orchestrator-assembled prompt — never the implementer's session.

A fresh process is the strongest available context isolation: the reviewer
cannot have seen the implementer's reasoning (concept §10.3 design note).
"""

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from harness.adapters.coding import AgentResult
from harness.adapters.text import TokenUsage
from harness.core.errors import AdapterError
from harness.sandbox import Sandbox

_IMPLEMENT_TOOLS = ("Read", "Edit", "Write", "Bash", "Glob", "Grep")
_REVIEW_TOOLS = ("Read", "Glob", "Grep")

# Best-effort deny-list for host-endangering Bash patterns (T-380). Read/
# Write/Edit are already scoped to the cwd by the CLI's own default file-
# tool confinement; Bash is a general shell and is not — these patterns
# block the most common ways an agent could escape the project root or
# damage the host. This is a documented residual risk, not a guarantee: a
# determined or confused agent can still find Bash invocations these
# patterns don't match. The concept's actual fix — running `claude` itself
# inside the sandbox container — is deferred: the agent's own process needs
# outbound network access to reach the Anthropic API, which conflicts with
# the container's default `network: []` (built for isolating untrusted
# *test* execution, not the agent's necessary API calls); resolving that
# conflict is a follow-up (concept §20-adjacent).
_DISALLOWED_BASH_PATTERNS = (
    "Bash(rm -rf /*)",
    "Bash(rm -rf /)",
    "Bash(rm -rf ~*)",
    "Bash(sudo:*)",
    "Bash(cd /)",
    "Bash(> /dev/sda)",
    "Bash(curl * | sh)",
    "Bash(curl * | bash)",
)

ProcessRunner = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]

# `claude -p --output-format json` emits one JSON envelope: {"type": "result",
# "subtype": "success" | "error_*", "is_error": bool, "result": "<final text>",
# "session_id": str, "total_cost_usd": float, "usage": {"input_tokens": int,
# "output_tokens": int, ...}} (T-340; verified against the installed CLI's
# documented schema at implementation time — re-verify if the CLI changes it).
_VERDICT_OBJECT_RE = re.compile(r"\{.*\"pass\"\s*:.*\}", re.DOTALL)


@dataclass(frozen=True)
class ReviewResult:
    passed: bool
    reasons: list[str]
    usage: TokenUsage


def _make_default_process_runner(timeout_s: float) -> ProcessRunner:
    def runner(command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(  # noqa: S603 -- command is built, not user-shell input
            command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout_s
        )

    return runner


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str):
        return int(value)
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    return default


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in cast("list[object]", value)]


def _usage_from_envelope(envelope: dict[str, object]) -> TokenUsage:
    usage_obj = envelope.get("usage")
    usage_dict = cast("dict[str, object]", usage_obj) if isinstance(usage_obj, dict) else {}
    return TokenUsage(
        input_tokens=_as_int(usage_dict.get("input_tokens")),
        output_tokens=_as_int(usage_dict.get("output_tokens")),
    )


def _envelope_is_error(envelope: dict[str, object]) -> bool:
    if "is_error" in envelope:
        return bool(envelope["is_error"])
    return envelope.get("subtype") != "success"


@dataclass
class ClaudeCodeAdapter:
    """`project_root` is the cwd for `review()` (which has no workdir
    parameter per the protocol it does not implement); `run()` receives its
    workdir explicitly, per `CodingAgentAdapter`. `process_runner` is
    injected so contract tests never spawn a real `claude` process; when
    omitted, the default runner enforces `command_timeout_s` (T-380)."""

    project_root: Path
    implement_model: str
    review_model: str
    command_timeout_s: float = 1800.0
    process_runner: ProcessRunner | None = None

    def __post_init__(self) -> None:
        if self.process_runner is None:
            self.process_runner = _make_default_process_runner(self.command_timeout_s)

    def run(self, workdir: Path, prompt: str, sandbox: Sandbox) -> AgentResult:
        sandbox.confine(workdir)
        command = [
            "claude",
            "-p",
            prompt,
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(_IMPLEMENT_TOOLS),
            "--disallowedTools",
            ",".join(_DISALLOWED_BASH_PATTERNS),
            "--model",
            self.implement_model,
            "--output-format",
            "json",
        ]
        completed = self._invoke(command, workdir)
        envelope = self._parse_json_or_raise(completed.stdout)

        return AgentResult(
            success=not _envelope_is_error(envelope),
            summary=str(envelope.get("result", completed.stdout)),
            usage=_usage_from_envelope(envelope),
            cost_usd=_as_float(envelope.get("total_cost_usd")),
        )

    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewResult:
        command = [
            "claude",
            "-p",
            prompt,
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(_REVIEW_TOOLS),
            "--model",
            self.review_model,
            "--output-format",
            "json",
        ]
        completed = self._invoke(command, self.project_root)
        envelope = self._parse_json(completed.stdout)
        result_text = str(envelope.get("result", "")) if envelope is not None else ""
        verdict = self._extract_verdict(result_text)

        if verdict is None:
            return ReviewResult(
                passed=False,
                reasons=["reviewer response was not a parseable {pass, reasons} verdict"],
                usage=TokenUsage(0, 0),
            )

        return ReviewResult(
            passed=bool(verdict["pass"]),
            reasons=_as_str_list(verdict.get("reasons", [])),
            usage=_usage_from_envelope(envelope) if envelope is not None else TokenUsage(0, 0),
        )

    @classmethod
    def _extract_verdict(cls, result_text: str) -> dict[str, object] | None:
        """The reviewer's `{"pass": bool, "reasons": [...]}` verdict lives
        *inside* the envelope's `result` text (the model's final message),
        not at the envelope's top level (T-340). Accept it verbatim or
        embedded in surrounding prose/fencing."""
        whole = cls._parse_json(result_text)
        if whole is not None and "pass" in whole:
            return whole
        match = _VERDICT_OBJECT_RE.search(result_text)
        if match is not None:
            embedded = cls._parse_json(match.group(0))
            if embedded is not None and "pass" in embedded:
                return embedded
        return None

    def _invoke(self, command: list[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
        assert self.process_runner is not None  # guaranteed by __post_init__
        try:
            return self.process_runner(command, cwd)
        except subprocess.TimeoutExpired as exc:
            raise AdapterError(
                f"claude -p timed out after {self.command_timeout_s}s running {command}"
            ) from exc
        except OSError as exc:
            raise AdapterError(f"failed to invoke claude -p: {exc}") from exc

    @staticmethod
    def _parse_json(text: str) -> dict[str, object] | None:
        try:
            parsed: object = json.loads(text)
        except json.JSONDecodeError:
            return None
        return cast("dict[str, object]", parsed) if isinstance(parsed, dict) else None

    def _parse_json_or_raise(self, text: str) -> dict[str, object]:
        parsed = self._parse_json(text)
        if parsed is None:
            raise AdapterError(f"claude -p returned non-JSON output: {text!r}")
        return parsed
