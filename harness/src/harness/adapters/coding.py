"""The seam between the orchestrator and the coding agent driving the
implementation stage (concept §13). `run()` carries out one ticket's
implementation inside the given sandbox and returns the outcome plus
usage/cost so the run log and budget guard have the numbers they need.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from harness.adapters.text import TokenUsage
from harness.sandbox import Sandbox


@dataclass(frozen=True)
class AgentResult:
    success: bool
    summary: str
    usage: TokenUsage
    cost_usd: float


class CodingAgentAdapter(Protocol):
    """Anything that can drive a coding agent over a workdir under a sandbox."""

    def run(self, workdir: Path, prompt: str, sandbox: Sandbox) -> AgentResult: ...
