"""Stage 1a — architectural concept (concept §6): bounded, structured
brainstorming; write the concept; self-review; declare phasing.

`run()` ignores the orchestrator-supplied `rendered_prompt` for the bulk of
its work — unlike the single-call stages (guidelines, tickets), Stage 1a is
an inherently multi-step interactive process (brainstorm round(s), then
concept-write, then self-review round(s)), so it renders its own sequence of
named templates internally via `prompts.render_prompt()`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from harness.adapters.text import TextStageAdapter
from harness.core.errors import StageError
from harness.folder import ProjectFolder
from harness.prompts import DEFAULT_TEMPLATE_VERSION, render_prompt
from harness.stages.base import StageResult, declared_io_for

READINESS_CHECKLIST: dict[str, tuple[str, ...]] = {
    "component breakdown and responsibilities": ("component",),
    "data model / key entities": ("data model", "key entities"),
    "external interfaces and integrations": ("external interface", "integration"),
    "technology stack": ("technology stack", "tech stack"),
    "major data and control flows": ("data flow", "control flow"),
    "phasing decision": ("phasing", "phase"),
}

_BLOCKING_HEADING = "## decisions needed"
_PHASING_SECTION_RE = re.compile(r"##\s*phasing(.*?)(?=\n##\s|\Z)", re.IGNORECASE | re.DOTALL)
_YAML_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL)
_NO_PHASING_PHRASES = ("no phasing", "none needed", "phasing is not")


def parse_blocking_questions(open_questions_md: str) -> list[str]:
    """Bullet items under '## Decisions needed (blocking)' until the next
    '##' heading (or end of text)."""
    items: list[str] = []
    in_section = False
    for raw_line in open_questions_md.splitlines():
        stripped = raw_line.strip()
        if stripped.lower().startswith(_BLOCKING_HEADING):
            in_section = True
            continue
        if in_section and stripped.startswith("##"):
            break
        if in_section and stripped.startswith("-"):
            items.append(stripped.lstrip("-").strip())
    return items


def missing_readiness_items(concept_md: str) -> list[str]:
    """Names of readiness-checklist items (concept §6.4) not evidenced in
    `concept_md`. Empty means the concept is ready."""
    lower = concept_md.lower()
    return [
        name
        for name, needles in READINESS_CHECKLIST.items()
        if not any(needle in lower for needle in needles)
    ]


def _validate_phasing_structure(value: object) -> None:
    if not isinstance(value, dict) or "phases" not in value:
        raise StageError("phasing.yaml block is malformed: missing 'phases'")
    parsed = cast("dict[str, object]", value)
    raw_phases = parsed["phases"]
    if not isinstance(raw_phases, list):
        raise StageError("phasing.yaml 'phases' must be a list")
    phases = cast("list[object]", raw_phases)
    if not phases:
        return
    active_count = sum(
        1
        for p in phases
        if isinstance(p, dict) and cast("dict[str, object]", p).get("active") is True
    )
    if active_count != 1:
        raise StageError(
            f"phasing.yaml must mark exactly one phase active when phases are declared, "
            f"found {active_count}"
        )
    if "stop_after_active_phase" not in parsed:
        raise StageError("phasing.yaml must set 'stop_after_active_phase' when phases are declared")


def extract_phasing_yaml(concept_md: str) -> str:
    """Extract the `phasing.yaml` content from the concept's '## Phasing'
    section: either a fenced YAML block, or an explicit "no phasing needed"
    statement (concept §6.3)."""
    match = _PHASING_SECTION_RE.search(concept_md)
    if match is None:
        raise StageError("concept.md has no '## Phasing' section (concept §6.4 readiness)")

    section = match.group(1)
    fence_match = _YAML_FENCE_RE.search(section)
    if fence_match is not None:
        yaml_text = fence_match.group(1).strip() + "\n"
        _validate_phasing_structure(yaml.safe_load(yaml_text))
        return yaml_text

    if any(phrase in section.lower() for phrase in _NO_PHASING_PHRASES):
        return "phases: []\nstop_after_active_phase: false\n"

    raise StageError(
        "concept.md's Phasing section is neither a phasing.yaml block nor an "
        "explicit 'no phasing needed' statement"
    )


def run_bounded_resolution_loop(
    *,
    generate_questions: Callable[[str], str],
    ask_user: Callable[[str], str],
    max_rounds: int,
) -> tuple[str, list[str]]:
    """Repeatedly generate structured questions and resolve blocking items
    via `ask_user`, until none remain or `max_rounds` is exhausted — in which
    case explicit assumptions are recorded instead, guaranteeing termination
    (concept §6.1).

    `generate_questions` receives the accumulated transcript of prior
    rounds' questions and answers (empty string on the first round) so the
    model actually incorporates the user's answers (T-350) rather than
    regenerating the same questions every round. The user gets exactly
    `max_rounds` answer opportunities before exhaustion — not `max_rounds -
    1` and not zero when `max_rounds == 1` (both were bugs; see
    DECISIONS.md T-350)."""
    resolutions: list[str] = []
    transcript = ""
    questions_text = ""
    blocking: list[str] = []

    for round_number in range(1, max_rounds + 1):
        questions_text = generate_questions(transcript)
        blocking = parse_blocking_questions(questions_text)
        if not blocking:
            return questions_text, resolutions

        answer = ask_user(questions_text)
        resolutions.append(answer)
        transcript += (
            f"\n\n## Round {round_number}\nQuestions:\n{questions_text}\n\nAnswer:\n{answer}"
        )

    assumptions = "\n".join(f"- {item}" for item in blocking)
    resolutions.append(f"Assumptions recorded after exhausting brainstorm rounds:\n{assumptions}")
    return questions_text, resolutions


@dataclass
class ConceptStage:
    folder: ProjectFolder
    max_rounds: int
    ask_user: Callable[[str], str]
    prompt_version: str = DEFAULT_TEMPLATE_VERSION
    template_dir: Path | None = None
    regeneration_feedback: str | None = None

    @property
    def inputs(self) -> list[Path]:
        return [self.folder.requirements_md, self.folder.instructions_md]

    @property
    def outputs(self) -> list[Path]:
        return [
            self.folder.spec_concept_md,
            self.folder.spec_open_questions_md,
            self.folder.spec_phasing_yaml,
        ]

    def _render(self, name: str, variables: dict[str, str]) -> str:
        return render_prompt(name, self.prompt_version, variables, template_dir=self.template_dir)

    def run(
        self, folder: ProjectFolder, adapter: TextStageAdapter, rendered_prompt: str
    ) -> StageResult:
        guard = declared_io_for(self, folder)
        requirements = guard.read_text(folder.requirements_md) or ""
        instructions = guard.read_text(folder.instructions_md, required=False) or ""
        resolved: list[str] = []

        def generate_brainstorm_questions(transcript: str) -> str:
            prompt = self._render(
                "brainstorm",
                {
                    "requirements": requirements,
                    "instructions": instructions,
                    "qa_transcript": transcript or "(none yet — this is the first round)",
                },
            )
            files = {"requirements.md": requirements, "instructions.md": instructions}
            return adapter.generate(
                prompt, files, template_name="brainstorm", template_version=self.prompt_version
            ).text

        open_questions_text, brainstorm_resolutions = run_bounded_resolution_loop(
            generate_questions=generate_brainstorm_questions,
            ask_user=self.ask_user,
            max_rounds=self.max_rounds,
        )
        resolved.extend(brainstorm_resolutions)
        guard.write_text(folder.spec_open_questions_md, open_questions_text)

        concept_prompt = self._render(
            "concept_write",
            {"requirements": requirements, "resolved_questions": "\n\n".join(resolved) or "none"},
        )
        if self.regeneration_feedback is not None:
            concept_prompt += (
                "\n\n## Human feedback from a rejected prior attempt — address it:\n"
                f"{self.regeneration_feedback}"
            )
        concept_text = adapter.generate(
            concept_prompt,
            {"requirements.md": requirements},
            template_name="concept_write",
            template_version=self.prompt_version,
        ).text

        def generate_self_review(transcript: str) -> str:
            review_prompt = self._render(
                "concept_self_review",
                {
                    "concept": concept_text,
                    "qa_transcript": transcript or "(none yet — this is the first round)",
                },
            )
            return adapter.generate(
                review_prompt,
                {"concept.md": concept_text},
                template_name="concept_self_review",
                template_version=self.prompt_version,
            ).text

        _, review_resolutions = run_bounded_resolution_loop(
            generate_questions=generate_self_review,
            ask_user=self.ask_user,
            max_rounds=self.max_rounds,
        )
        if review_resolutions:
            # One extra generate call folds the resolved feedback into a
            # coherent revised concept (T-350), via a dedicated template
            # (T-550) instead of reusing concept_self_review with a manual
            # instruction appended.
            revision_prompt = self._render(
                "concept_revise",
                {"concept": concept_text, "resolutions": "\n\n".join(review_resolutions)},
            )
            concept_text = adapter.generate(
                revision_prompt,
                {"concept.md": concept_text},
                template_name="concept_revise",
                template_version=self.prompt_version,
            ).text

        missing = missing_readiness_items(concept_text)
        if missing:
            raise StageError(f"concept is not ready: missing {missing}")

        phasing_yaml = extract_phasing_yaml(concept_text)

        guard.write_text(folder.spec_concept_md, concept_text)
        guard.write_text(folder.spec_phasing_yaml, phasing_yaml)

        return StageResult(
            outputs_written=[
                folder.spec_open_questions_md,
                folder.spec_concept_md,
                folder.spec_phasing_yaml,
            ]
        )
