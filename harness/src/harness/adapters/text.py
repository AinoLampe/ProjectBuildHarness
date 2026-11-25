"""The seam decoupling text stages (concept, guidelines, tickets) from any
provider (concept §13). `generate()` receives only the prompt and the
declared input files' content — never ambient context — and returns the
generated text *and* token usage, which the run log and budget guard need.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class GenerationResult:
    text: str
    usage: TokenUsage


class TextStageAdapter(Protocol):
    """Anything that can turn a prompt + declared input files into text.

    `template_name`/`template_version` are optional identity metadata for
    the prompt being rendered (T-310) — implementations are not required to
    act on them, but a recording wrapper (the orchestrator's) uses them to
    attribute `run.log` entries to the template that produced the call."""

    def generate(
        self,
        prompt: str,
        files: dict[str, str],
        *,
        template_name: str = "",
        template_version: str = "",
    ) -> GenerationResult: ...
