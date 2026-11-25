"""Reference `CodingAgentAdapter` double: simulates writing `src/` (and
journal) files from a script, no real agent or spend (guidelines §4.3)."""

from dataclasses import dataclass, field
from pathlib import Path

from harness.adapters.coding import AgentResult
from harness.core.errors import AdapterError
from harness.sandbox import Sandbox


@dataclass(frozen=True)
class ScriptedRun:
    """One scripted `run()` outcome: files to write (relative-path ->
    content) plus the `AgentResult` to return."""

    result: AgentResult
    writes: dict[str, str] = field(default_factory=dict[str, str])


class FakeCodingAgent:
    """Returns each scripted `ScriptedRun` in order, writing its `writes`
    relative to `workdir` first; a scripted `Exception` is raised wrapped as
    `AdapterError`. Records every call (workdir, prompt) for assertions."""

    def __init__(self, script: list[ScriptedRun | Exception]) -> None:
        self._script = list(script)
        self._index = 0
        self.calls: list[tuple[Path, str]] = []

    def run(self, workdir: Path, prompt: str, sandbox: Sandbox) -> AgentResult:
        self.calls.append((workdir, prompt))
        if self._index >= len(self._script):
            raise AdapterError("FakeCodingAgent script exhausted")

        next_item = self._script[self._index]
        self._index += 1

        if isinstance(next_item, Exception):
            raise AdapterError(str(next_item)) from next_item

        for relative_path, content in next_item.writes.items():
            target = sandbox.confine(workdir / relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        return next_item.result
