"""Stage 3 — implementation driver (concept §10): drive the coding agent
through the tickets in dependency order, gate each with the review gate
(T-200), retry-then-escalate on failure, journal everything, and close the
loop with a final acceptance pass against the original requirements.
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

from harness.adapters.coding import AgentResult, CodingAgentAdapter
from harness.core.clock import Clock
from harness.core.errors import EscalationRequired, StageError
from harness.dag import TicketNode, normalise_ticket_id, topological_order
from harness.folder import ProjectFolder
from harness.freeze import is_stale, read_frozen
from harness.journal import (
    DecisionRecord,
    EscalationRecord,
    ProgressEntry,
    latest_escalation_for,
    record_decision,
    record_escalation,
    record_progress,
    resume_state,
)
from harness.prompts import DEFAULT_TEMPLATE_VERSION, render_prompt
from harness.sandbox import Sandbox
from harness.stages.base import StageResult, declared_io_for
from harness.stages.review import ReviewerAdapter, run_objective_checks, run_review_gate

_CONNECTIONS_LINE_RE = re.compile(r"-\s*(depends on|blocks)\s*:\s*(.*)", re.IGNORECASE)
_FILENAME_NUMBER_RE = re.compile(r"^(\d{3})")
_TESTS_SECTION_RE = re.compile(r"###\s*Tests\s*\n(.*?)(?=\n##|\Z)", re.IGNORECASE | re.DOTALL)
_BULLET_LINE_RE = re.compile(r"^-\s*(.+)$")
FINAL_ACCEPTANCE_MARKER = "__final_acceptance__"


@dataclass(frozen=True)
class TicketSpec:
    id: str
    path: Path
    text: str
    depends_on: list[str]
    blocks: list[str]
    test_paths: list[str] = field(default_factory=list[str])


def _parse_ids(raw: str) -> list[str]:
    """Normalise each Connections reference to this module's `T-NNN` id
    shape, regardless of how the ticket spells it (`010`, `T-010`,
    `010-slug`) — T-360. A reference to the overview (`000`) is dropped: it
    is never an implementable node in Stage 3's build order."""
    ids: list[str] = []
    for item in raw.split(","):
        if not item.strip():
            continue
        normalised = normalise_ticket_id(item)
        if normalised == "000":
            continue
        ids.append(f"T-{normalised}")
    return ids


def _parse_test_paths(text: str) -> list[str]:
    """Bullet-listed paths under a ticket's `### Tests` section (T-520) —
    the test files/dirs the review gate should run *for this ticket*
    instead of the whole suite. Optional: a ticket without this section
    falls back to the full suite for its own gate (unchanged v0 behaviour),
    but the final full-suite pass at the end of the stage always runs
    regardless."""
    match = _TESTS_SECTION_RE.search(text)
    if match is None:
        return []
    paths: list[str] = []
    for line in match.group(1).splitlines():
        bullet_match = _BULLET_LINE_RE.match(line.strip())
        if bullet_match:
            paths.append(bullet_match.group(1).strip())
    return paths


def parse_ticket_file(path: Path, text: str) -> TicketSpec:
    """Derive a ticket's id from its filename (`0NN-*.md` -> `T-0NN`) and
    extract its Connections (`depends on` / `blocks`) and declared test
    scope (`### Tests`, T-520)."""
    match = _FILENAME_NUMBER_RE.match(path.stem)
    number = match.group(1) if match else path.stem[:3]
    depends_on: list[str] = []
    blocks: list[str] = []
    for line in text.splitlines():
        connection_match = _CONNECTIONS_LINE_RE.match(line.strip())
        if connection_match is None:
            continue
        kind, ids_text = connection_match.group(1).lower(), connection_match.group(2)
        if kind == "depends on":
            depends_on = _parse_ids(ids_text)
        elif kind == "blocks":
            blocks = _parse_ids(ids_text)
    return TicketSpec(
        id=f"T-{number}",
        path=path,
        text=text,
        depends_on=depends_on,
        blocks=blocks,
        test_paths=_parse_test_paths(text),
    )


def plan_build_order(specs: list[TicketSpec]) -> list[str]:
    """The topological build order over `specs` (T-080); raises
    `DagCycleError` on a cyclic Connections graph."""
    nodes = [
        TicketNode(id=spec.id, depends_on=list(spec.depends_on), blocks=list(spec.blocks))
        for spec in specs
    ]
    return topological_order(nodes)


def snapshot_tree(root: Path) -> dict[Path, tuple[int, int]]:
    """path -> (mtime_ns, size) for every file under `root` (T-520) — a
    before/after diff of this is how the reviewer learns exactly which
    files an agent call touched, instead of being told "everything in
    src/ changed" on every ticket regardless of what actually happened.
    Size is included alongside mtime because some filesystems' mtime
    resolution is too coarse to distinguish two writes within the same
    tick."""
    if not root.is_dir():
        return {}
    stats = ((p, p.stat()) for p in root.rglob("*") if p.is_file())
    return {p: (stat.st_mtime_ns, stat.st_size) for p, stat in stats}


def diff_changed_paths(
    before: dict[Path, tuple[int, int]], after: dict[Path, tuple[int, int]]
) -> list[Path]:
    return sorted(p for p, fingerprint in after.items() if before.get(p) != fingerprint)


@dataclass
class ImplementStage:
    folder: ProjectFolder
    frozen_version: str
    clock: Clock
    sandbox: Sandbox
    reviewer: ReviewerAdapter
    retry_budget: int = 2
    prompt_version: str = DEFAULT_TEMPLATE_VERSION
    template_dir: Path | None = None
    require_tests_green: bool = True
    require_llm_review: bool = True

    @property
    def inputs(self) -> list[Path]:
        version_dir = self.folder.spec_lock_dir / self.frozen_version
        ticket_paths = sorted(
            p for p in self.folder.spec_tickets_dir.glob("*.md") if p.name != "000-overview.md"
        )
        return [
            version_dir / "concept.md",
            version_dir / "guidelines.md",
            self.folder.requirements_md,
            *ticket_paths,
        ]

    @property
    def outputs(self) -> list[Path]:
        return [
            self.folder.journal_decisions_md,
            self.folder.journal_decisions_json,
            self.folder.journal_progress_md,
            self.folder.journal_progress_json,
        ]

    @property
    def _frozen_version_dir(self) -> Path:
        return self.folder.spec_lock_dir / self.frozen_version

    def _render_bootstrap(self, ticket_id: str, ticket_text: str) -> str:
        return render_prompt(
            "implement_bootstrap",
            self.prompt_version,
            {
                "ticket_id": ticket_id,
                "ticket_text": ticket_text,
                "frozen_concept_path": str(self._frozen_version_dir / "concept.md"),
                "frozen_guidelines_path": str(self._frozen_version_dir / "guidelines.md"),
                "overview_path": str(self.folder.spec_tickets_dir / "000-overview.md"),
                "journal_dir": str(self.folder.journal_dir),
            },
            template_dir=self.template_dir,
        )

    def _render_retry(self, original_prompt: str, reasons: list[str]) -> str:
        return render_prompt(
            "implement_retry",
            self.prompt_version,
            {"original_prompt": original_prompt, "reasons": "; ".join(reasons)},
            template_dir=self.template_dir,
        )

    def _render_final_acceptance(self, requirements_text: str, frozen_concept: str) -> str:
        return render_prompt(
            "final_acceptance",
            self.prompt_version,
            {"requirements": requirements_text, "frozen_concept": frozen_concept},
            template_dir=self.template_dir,
        )

    def _implement_one_ticket(self, adapter: CodingAgentAdapter, spec: TicketSpec) -> AgentResult:
        open_escalation = latest_escalation_for(self.folder, spec.id)
        if open_escalation is not None and open_escalation.resolution is None:
            # T-530: never silently re-attempt a ticket with an unresolved
            # escalation — that would thrash the same failure every run.
            raise EscalationRequired(
                f"{spec.id} has an open escalation from a previous run; resolve it with "
                f"`harness resolve --ticket {spec.id} --answer ...` before running again: "
                f"{open_escalation.context}"
            )

        prompt = self._render_bootstrap(spec.id, spec.text)
        if open_escalation is not None and open_escalation.resolution is not None:
            # a resolved escalation gets a fresh retry budget (below) and
            # the human's answer folded into the bootstrap prompt
            prompt += (
                "\n\n## Human resolution for a previous escalation on this ticket:\n"
                f"{open_escalation.resolution}"
            )

        attempt = 0
        max_attempts = self.retry_budget + 1

        while True:
            attempt += 1
            before = snapshot_tree(self.folder.src_dir)
            agent_result = adapter.run(self.folder.root, prompt, self.sandbox)
            changed_paths = diff_changed_paths(before, snapshot_tree(self.folder.src_dir))
            gate_result = asyncio.run(
                run_review_gate(
                    ticket_id=spec.id,
                    ticket_text=spec.text,
                    test_paths=spec.test_paths,
                    changed_paths=changed_paths or [self.folder.src_dir],
                    sandbox=self.sandbox,
                    adapter=self.reviewer,
                    prompt_version=self.prompt_version,
                    template_dir=self.template_dir,
                    require_tests_green=self.require_tests_green,
                    require_llm_review=self.require_llm_review,
                    concept_path=str(self._frozen_version_dir / "concept.md"),
                    guidelines_path=str(self._frozen_version_dir / "guidelines.md"),
                )
            )
            if gate_result.passed:
                return agent_result
            if attempt >= max_attempts:
                record_escalation(
                    self.folder,
                    EscalationRecord(
                        timestamp=self.clock.now(),
                        kind="retry_exhausted",
                        ticket=spec.id,
                        context=(
                            f"failed the review gate after {attempt} attempt(s). "
                            f"Reasons: {gate_result.reasons}"
                        ),
                    ),
                )
                raise EscalationRequired(
                    f"{spec.id} failed the review gate after {attempt} attempt(s); "
                    f"escalating to the user. Reasons: {gate_result.reasons}"
                )
            prompt = self._render_retry(prompt, gate_result.reasons)

    def run(
        self, folder: ProjectFolder, adapter: CodingAgentAdapter, rendered_prompt: str
    ) -> StageResult:
        guard = declared_io_for(self, folder)
        if is_stale(folder, self.frozen_version):
            raise StageError(
                f"frozen spec version {self.frozen_version} has been superseded by a later "
                "freeze; re-run against the current frozen version (T-330)"
            )
        if not self.require_tests_green and not self.require_llm_review:
            record_decision(
                folder,
                DecisionRecord(
                    timestamp=self.clock.now(),
                    ticket=None,
                    conflict=(
                        "implementation.review.require_tests_green and require_llm_review "
                        "are both false"
                    ),
                    resolution=(
                        "every ticket's review gate in this run passes trivially, with no "
                        "automated checks and no LLM review"
                    ),
                    reasoning=(
                        "explicit project configuration (T-400) — recorded here so the gap "
                        "is visible in the audit trail rather than silent"
                    ),
                ),
            )
        frozen = read_frozen(folder, self.frozen_version)
        requirements_text = guard.read_text(folder.requirements_md) or ""

        ticket_paths = sorted(
            p for p in folder.spec_tickets_dir.glob("*.md") if p.name != "000-overview.md"
        )
        specs = {
            spec.id: spec
            for spec in (parse_ticket_file(p, guard.read_text(p) or "") for p in ticket_paths)
        }
        order = plan_build_order(list(specs.values()))

        state = resume_state(
            folder, all_units=[*order, FINAL_ACCEPTANCE_MARKER], frozen_version=self.frozen_version
        )
        completed = set(state.completed)

        implemented_any = False
        for ticket_id in order:
            if ticket_id in completed:
                continue
            implemented_any = True
            spec = specs[ticket_id]
            agent_result = self._implement_one_ticket(adapter, spec)
            record_progress(
                folder,
                ProgressEntry(
                    timestamp=self.clock.now(),
                    ticket=ticket_id,
                    summary=agent_result.summary,
                    frozen_version=self.frozen_version,
                ),
            )

        if implemented_any and self.require_tests_green:
            # T-520: each ticket's own gate only ran its declared test scope
            # (or the full suite, if it declared none) — one full-suite pass
            # here is the regression net across everything implemented in
            # this run, run once rather than on every single ticket.
            full_suite = run_objective_checks(self.sandbox, [])
            if not full_suite.all_passed:
                raise StageError(
                    "final full-suite regression check failed after all tickets passed "
                    f"their individual gates:\n{full_suite.output}"
                )

        blocking_questions: list[str] = []
        if FINAL_ACCEPTANCE_MARKER not in completed:
            final_prompt = self._render_final_acceptance(requirements_text, frozen.concept_text)
            # read-only: validating the assembled implementation is a judgment
            # call, not an edit — uses the reviewer path (T-410), never the
            # write-capable implementer.
            final_verdict = self.reviewer.review(
                FINAL_ACCEPTANCE_MARKER, [folder.src_dir], frozen.concept_text, "", final_prompt
            )
            summary = (
                "; ".join(final_verdict.reasons) if final_verdict.reasons else "no drift found"
            )
            record_progress(
                folder,
                ProgressEntry(
                    timestamp=self.clock.now(),
                    ticket=FINAL_ACCEPTANCE_MARKER,
                    summary=summary,
                    frozen_version=self.frozen_version,
                ),
            )
            if not final_verdict.passed:
                record_escalation(
                    folder,
                    EscalationRecord(
                        timestamp=self.clock.now(),
                        kind="drift",
                        ticket=None,
                        context=f"final acceptance pass found drift: {summary}",
                    ),
                )
                blocking_questions = [f"Final acceptance pass found drift: {summary}"]

        return StageResult(
            outputs_written=[
                folder.journal_progress_md,
                folder.journal_progress_json,
            ],
            blocking_questions=blocking_questions,
        )
