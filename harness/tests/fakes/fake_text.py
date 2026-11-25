"""Reference `TextStageAdapter` double: scripted outputs/usage, no network,
no spend. The workhorse for stage and orchestration tests (guidelines §4.3).
"""

from harness.adapters.text import GenerationResult
from harness.core.errors import AdapterError


class FakeTextAdapter:
    """Returns each scripted `GenerationResult` in order; a scripted
    `Exception` is raised wrapped as `AdapterError`. Records every call
    (prompt, files) for assertions in stage/orchestration tests."""

    def __init__(self, script: list[GenerationResult | Exception]) -> None:
        self._script = list(script)
        self._index = 0
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.templates: list[tuple[str, str]] = []

    def generate(
        self,
        prompt: str,
        files: dict[str, str],
        *,
        template_name: str = "",
        template_version: str = "",
    ) -> GenerationResult:
        self.calls.append((prompt, dict(files)))
        self.templates.append((template_name, template_version))
        if self._index >= len(self._script):
            raise AdapterError("FakeTextAdapter script exhausted")

        next_item = self._script[self._index]
        self._index += 1

        if isinstance(next_item, Exception):
            raise AdapterError(str(next_item)) from next_item
        return next_item
