"""Stage 1b — engineering guidelines (concept §7): generate guidelines from
the concept in a fresh context (no brainstorming history — the stage's only
input is `concept.md`), then consolidate, with the concept winning any
conflict."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.adapters.text import TextStageAdapter
from harness.contracts import ConsolidationVerdict, parse_structured
from harness.core.clock import Clock
from harness.folder import ProjectFolder
from harness.journal import DecisionRecord, record_decision
from harness.prompts import DEFAULT_TEMPLATE_VERSION, render_prompt
from harness.stages.base import StageResult, declared_io_for


def parse_consolidation(
    text: str, *, re_ask: Callable[[str], str] | None = None
) -> ConsolidationVerdict:
    """Parse the consolidation step's structured JSON verdict (T-500):
    `conflict_found` is a first-class boolean the model sets explicitly —
    no more matching the conflict description against a fixed "no
    conflict" phrase list (the historical bug: a model answering "No
    conflicts found." was recorded as a **conflict** because that exact
    phrase wasn't on the list)."""
    return parse_structured(text, ConsolidationVerdict, re_ask=re_ask)


@dataclass
class GuidelinesStage:
    folder: ProjectFolder
    clock: Clock
    prompt_version: str = DEFAULT_TEMPLATE_VERSION
    template_dir: Path | None = None
    regeneration_feedback: str | None = None

    @property
    def inputs(self) -> list[Path]:
        return [self.folder.spec_concept_md]

    @property
    def outputs(self) -> list[Path]:
        return [
            self.folder.spec_guidelines_md,
            self.folder.spec_concept_md,
            self.folder.journal_decisions_md,
            self.folder.journal_decisions_json,
        ]

    def _render(self, name: str, variables: dict[str, str]) -> str:
        return render_prompt(name, self.prompt_version, variables, template_dir=self.template_dir)

    def run(
        self, folder: ProjectFolder, adapter: TextStageAdapter, rendered_prompt: str
    ) -> StageResult:
        guard = declared_io_for(self, folder)
        concept_text = guard.read_text(folder.spec_concept_md) or ""

        guidelines_prompt = self._render("guidelines", {"concept": concept_text})
        if self.regeneration_feedback is not None:
            guidelines_prompt += (
                "\n\n## Human feedback from a rejected prior attempt — address it:\n"
                f"{self.regeneration_feedback}"
            )
        guidelines_text = adapter.generate(
            guidelines_prompt,
            {"concept.md": concept_text},
            template_name="guidelines",
            template_version=self.prompt_version,
        ).text
        guard.write_text(folder.spec_guidelines_md, guidelines_text)

        consolidation_prompt = self._render(
            "guidelines_consolidation", {"concept": concept_text, "guidelines": guidelines_text}
        )
        consolidation_files = {"concept.md": concept_text, "guidelines.md": guidelines_text}
        consolidation_text = adapter.generate(
            consolidation_prompt,
            consolidation_files,
            template_name="guidelines_consolidation",
            template_version=self.prompt_version,
        ).text

        def _re_ask(followup: str) -> str:
            return adapter.generate(
                followup,
                consolidation_files,
                template_name="guidelines_consolidation",
                template_version=self.prompt_version,
            ).text

        outcome = parse_consolidation(consolidation_text, re_ask=_re_ask)

        outputs_written = [folder.spec_guidelines_md]

        if outcome.conflict_found:
            record_decision(
                folder,
                DecisionRecord(
                    timestamp=self.clock.now(),
                    ticket=None,
                    conflict=outcome.conflict or "",
                    resolution=outcome.resolution or "",
                    reasoning="concept outranks guidelines (concept §7)",
                ),
            )
            outputs_written += [folder.journal_decisions_md, folder.journal_decisions_json]

            if outcome.revised_concept is not None:
                guard.write_text(folder.spec_concept_md, outcome.revised_concept)
                outputs_written.append(folder.spec_concept_md)

        return StageResult(outputs_written=outputs_written)
