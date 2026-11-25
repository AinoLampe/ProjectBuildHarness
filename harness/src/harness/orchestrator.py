"""Orchestrator state machine: `concept -> guidelines -> freeze -> tickets ->
implement` (concept §2, §5). The orchestrator does not "think" — it
sequences stages and applies, *around* each one, model routing, prompt
rendering, gates, recording, and budget tracking.
"""

import hashlib
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from harness.adapters.coding import AgentResult, CodingAgentAdapter
from harness.adapters.text import GenerationResult, TextStageAdapter
from harness.budget import BudgetGuard, estimate_tokens_from_text
from harness.config import HarnessConfig
from harness.core.clock import Clock
from harness.core.errors import EscalationRequired, GateRejected
from harness.folder import ProjectFolder
from harness.freeze import freeze_spec, latest_version, read_frozen
from harness.gates import GateIO, GatePolicy, apply_gate
from harness.journal import (
    DecisionRecord,
    GateOutcome,
    RunLogEntry,
    append_run_log,
    latest_gate_outcome,
    record_decision,
    record_gate_outcome,
)
from harness.sandbox import Sandbox
from harness.stages.concept import ConceptStage
from harness.stages.guidelines import GuidelinesStage
from harness.stages.implement import ImplementStage
from harness.stages.review import ReviewerAdapter, ReviewerVerdictLike
from harness.stages.tickets import TicketsStage


def _no_op_warning(message: str) -> None:
    return None


@dataclass(frozen=True)
class OrchestratorResult:
    completed_stages: list[str]
    halted: bool
    halt_reason: str | None
    # Non-fatal findings surfaced after a successful run — currently just
    # the final acceptance pass's drift report (T-410), if any.
    warnings: list[str] = field(default_factory=list[str])


def _sha256_bytes_file(path: Path) -> str:
    """Hash a file's raw bytes — used for run.log's informational
    stage-artifact record, which may include binary outputs (`tickets.zip`)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Worst-case output-token ceiling used for the pre-call headroom check
# (T-370). A placeholder matching AnthropicTextAdapter's own default until
# T-420 makes max_tokens configurable per stage and threads the real value
# through here.
_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE = 4096


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_text_file(path: Path) -> str:
    """Hash the *decoded text*, not raw bytes: text-mode I/O translates
    newlines on write (`\\n` -> the platform line separator), so hashing raw
    bytes would make the same logical content hash differently across
    platforms and mismatch the hash recorded from an in-memory string
    (T-320). Only used for gate-approval hashes, which are always over
    text artifacts (concept/guidelines/overview markdown)."""
    return _sha256_text(path.read_text(encoding="utf-8"))


@dataclass
class _RecordingTextAdapter:
    """Wraps a `TextStageAdapter` to budget-track *and* run-log every call
    (T-310): one `RunLogEntry` per `generate()`, plus a `"budget_warning"`
    event entry the first time cumulative spend crosses `warn_at_usd`."""

    inner: TextStageAdapter
    guard: BudgetGuard
    model: str
    stage: str
    folder: ProjectFolder
    clock: Clock
    on_warning: Callable[[str], None] = field(default=_no_op_warning)

    def generate(
        self,
        prompt: str,
        files: dict[str, str],
        *,
        template_name: str = "",
        template_version: str = "",
    ) -> GenerationResult:
        est_input_tokens = estimate_tokens_from_text(prompt) + sum(
            estimate_tokens_from_text(text) for text in files.values()
        )
        self.guard.check_headroom(
            self.model,
            est_input_tokens=est_input_tokens,
            max_output_tokens=_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE,
        )

        start = time.perf_counter()
        result = self.inner.generate(
            prompt, files, template_name=template_name, template_version=template_version
        )
        elapsed = time.perf_counter() - start
        usage_result = self.guard.record_usage(
            self.model,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
        append_run_log(
            self.folder,
            RunLogEntry(
                timestamp=self.clock.now(),
                stage=self.stage,
                provider_or_agent="anthropic",
                model=self.model,
                prompt_template=template_name,
                prompt_version=template_version,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                estimated_cost_usd=usage_result.cost_usd,
                wall_time_s=elapsed,
            ),
        )
        if usage_result.warned:
            message = (
                f"budget warning: cumulative spend ${usage_result.total_spent_usd:.4f} "
                f"has crossed the warn threshold"
            )
            self.on_warning(message)
            append_run_log(
                self.folder,
                RunLogEntry(
                    timestamp=self.clock.now(),
                    stage=self.stage,
                    provider_or_agent="anthropic",
                    model=self.model,
                    prompt_template="-",
                    prompt_version="-",
                    input_tokens=0,
                    output_tokens=0,
                    estimated_cost_usd=0.0,
                    wall_time_s=0.0,
                    event="budget_warning",
                ),
            )
        return result


@dataclass
class _RecordingCodingAdapter:
    """Wraps a `CodingAgentAdapter` to run-log each `run()` call and route
    its self-reported cost into the same `BudgetGuard` ledger as the text
    stages (T-510; previously tracked in run.log only — see DECISIONS.md
    T-220/T-310 for why this couldn't just reuse the rate-table path)."""

    inner: CodingAgentAdapter
    model: str
    folder: ProjectFolder
    clock: Clock
    guard: BudgetGuard

    def run(self, workdir: Path, prompt: str, sandbox: Sandbox) -> AgentResult:
        start = time.perf_counter()
        result = self.inner.run(workdir, prompt, sandbox)
        elapsed = time.perf_counter() - start
        append_run_log(
            self.folder,
            RunLogEntry(
                timestamp=self.clock.now(),
                stage="implement",
                provider_or_agent="claude-code",
                model=self.model,
                prompt_template="implement_bootstrap",
                prompt_version="-",
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                estimated_cost_usd=result.cost_usd,
                wall_time_s=elapsed,
            ),
        )
        self.guard.record_direct_cost("implement.run", result.cost_usd)
        return result


@dataclass
class _RecordingReviewerAdapter:
    """Wraps a `ReviewerAdapter` to run-log each `review()` call and route
    its cost into the same `BudgetGuard` ledger (T-510). The current
    `ReviewResult` schema carries token usage but no self-reported cost, so
    the amount routed through the guard is 0.0 today (documented gap,
    DECISIONS.md T-310) — the plumbing is in place for when it isn't."""

    inner: ReviewerAdapter
    model: str
    folder: ProjectFolder
    clock: Clock
    guard: BudgetGuard

    def review(
        self,
        ticket: str,
        diff_paths: list[Path],
        criteria: str,
        objective_results: str,
        prompt: str,
    ) -> ReviewerVerdictLike:
        start = time.perf_counter()
        result = self.inner.review(ticket, diff_paths, criteria, objective_results, prompt)
        elapsed = time.perf_counter() - start
        usage = getattr(result, "usage", None)
        input_tokens = usage.input_tokens if usage is not None else 0
        output_tokens = usage.output_tokens if usage is not None else 0
        reviewer_cost = getattr(result, "cost_usd", 0.0)
        append_run_log(
            self.folder,
            RunLogEntry(
                timestamp=self.clock.now(),
                stage="implement",
                provider_or_agent="claude-code",
                model=self.model,
                prompt_template="review_gate",
                prompt_version="-",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                estimated_cost_usd=reviewer_cost,
                wall_time_s=elapsed,
            ),
        )
        self.guard.record_direct_cost(f"implement.review:{ticket}", reviewer_cost)
        return result


@dataclass
class Orchestrator:
    folder: ProjectFolder
    config: HarnessConfig
    clock: Clock
    concept_adapter: TextStageAdapter
    guidelines_adapter: TextStageAdapter
    tickets_adapter: TextStageAdapter
    coding_adapter: CodingAgentAdapter
    reviewer_adapter: ReviewerAdapter
    sandbox: Sandbox
    gate_io: GateIO
    ask_user: Callable[[str], str]
    budget_guard: BudgetGuard
    on_warning: Callable[[str], None] = field(default=_no_op_warning)

    def run(self) -> OrchestratorResult:
        completed: list[str] = []

        self._ensure_stage_gated(
            "concept",
            self.folder.spec_concept_md,
            self.config.gates.concept,
            self._generate_concept,
        )
        completed.append("concept")

        self._ensure_stage_gated(
            "guidelines",
            self.folder.spec_guidelines_md,
            self.config.gates.guidelines,
            self._generate_guidelines,
        )
        completed.append("guidelines")

        version = self._ensure_frozen()
        completed.append("freeze")

        overview_path = self.folder.spec_tickets_dir / "000-overview.md"
        self._ensure_stage_gated(
            "tickets",
            overview_path,
            self.config.gates.tickets,
            lambda feedback: self._generate_tickets(feedback, version),
        )
        completed.append("tickets")

        try:
            warnings = self._run_implement(version)
        except EscalationRequired as exc:
            # T-530: a clean halt, not a traceback — the caller (CLI) prints
            # this and points at `harness resolve` / `harness status`.
            return OrchestratorResult(
                completed_stages=completed,
                halted=True,
                halt_reason="escalation",
                warnings=[str(exc)],
            )
        completed.append("implement")

        if self._should_stop_at_phase_boundary():
            return OrchestratorResult(
                completed_stages=completed,
                halted=True,
                halt_reason="phase_boundary",
                warnings=warnings,
            )

        return OrchestratorResult(
            completed_stages=completed, halted=False, halt_reason=None, warnings=warnings
        )

    def _ensure_frozen(self) -> str:
        """Freeze the spec if nothing is frozen yet; if a frozen version
        already exists, compare it against the *current* concept/guidelines
        content and re-freeze — invalidating downstream outputs — only if
        they no longer match (T-330, concept §8/§16). An unchanged spec
        reuses the existing version (idempotent)."""
        current_version = latest_version(self.folder)
        if current_version is None:
            return freeze_spec(self.folder, self.clock).version

        frozen = read_frozen(self.folder, current_version)
        concept_text = self.folder.read_text(self.folder.spec_concept_md) or ""
        guidelines_text = self.folder.read_text(self.folder.spec_guidelines_md) or ""
        unchanged = (
            _sha256_text(concept_text) == frozen.concept_hash
            and _sha256_text(guidelines_text) == frozen.guidelines_hash
        )
        if unchanged:
            return current_version

        new_version = freeze_spec(self.folder, self.clock).version
        self._invalidate_downstream_of_freeze(current_version, new_version)
        return new_version

    def _invalidate_downstream_of_freeze(self, old_version: str, new_version: str) -> None:
        """Move tickets and `tickets.zip` aside into
        `spec/.invalidated/<new_version>/` — never delete — because they
        were built against a frozen spec that no longer matches what's on
        disk (T-330). Stage 2 will regenerate them against the new freeze;
        any Stage-3 progress recorded against `old_version` no longer
        counts as done (`resume_state(..., frozen_version=...)`, T-330)."""
        self._move_aside(new_version, self.folder.spec_tickets_dir, "tickets")
        self._move_aside(new_version, self.folder.root / "tickets.zip", "tickets.zip")
        record_decision(
            self.folder,
            DecisionRecord(
                timestamp=self.clock.now(),
                ticket=None,
                conflict=f"concept/guidelines changed after spec was frozen as {old_version}",
                resolution=(
                    f"re-froze as {new_version}; prior tickets/implementation progress for "
                    f"{old_version} invalidated (moved aside, not deleted) and will be rebuilt"
                ),
                reasoning=(
                    "the frozen spec is the build's source of truth (concept §8); once it "
                    "drifts from what's on disk, everything built against the old version "
                    "must be treated as stale rather than silently reused (concept §16)"
                ),
            ),
        )

    def _move_aside(self, version: str, path: Path, name: str) -> None:
        if not path.exists():
            return
        invalidated_dir = self.folder.spec_invalidated_dir / version
        invalidated_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(invalidated_dir / name))

    def invalidate_from(self, stage: str) -> None:
        """Force a full regeneration from `stage` onward, for `harness run
        --from <stage>` (T-330, concept §17): move `stage`'s artifact(s) —
        and everything they gate — aside into `spec/.invalidated/`, never
        deleting. The next `run()` regenerates them; re-freezing (and its
        own downstream invalidation) happens automatically once the concept/
        guidelines content actually changes."""
        version = f"manual-{self.clock.now().strftime('%Y%m%dT%H%M%SZ')}"
        if stage == "concept":
            self._move_aside(version, self.folder.spec_concept_md, "concept.md")
            self._move_aside(version, self.folder.spec_open_questions_md, "open-questions.md")
            self._move_aside(version, self.folder.spec_phasing_yaml, "phasing.yaml")
            self._move_aside(version, self.folder.spec_guidelines_md, "guidelines.md")
            self._move_aside(version, self.folder.spec_tickets_dir, "tickets")
            self._move_aside(version, self.folder.root / "tickets.zip", "tickets.zip")
        elif stage == "guidelines":
            self._move_aside(version, self.folder.spec_guidelines_md, "guidelines.md")
            self._move_aside(version, self.folder.spec_tickets_dir, "tickets")
            self._move_aside(version, self.folder.root / "tickets.zip", "tickets.zip")
        elif stage == "tickets":
            self._move_aside(version, self.folder.spec_tickets_dir, "tickets")
            self._move_aside(version, self.folder.root / "tickets.zip", "tickets.zip")
        elif stage == "implement":
            self._move_aside(version, self.folder.journal_progress_md, "PROGRESS.md")
            self._move_aside(version, self.folder.journal_progress_json, "progress.json")

    def _should_stop_at_phase_boundary(self) -> bool:
        if self.config.gates.phase_boundary != "stop":
            return False
        phasing_text = self.folder.read_text(self.folder.spec_phasing_yaml, required=False)
        if not phasing_text:
            return False
        loaded: object = yaml.safe_load(phasing_text) or {}
        if not isinstance(loaded, dict):
            return False
        parsed = cast("dict[str, object]", loaded)
        return parsed.get("stop_after_active_phase") is True

    def _wrap_text_adapter(
        self, inner: TextStageAdapter, *, stage: str, model: str
    ) -> TextStageAdapter:
        return _RecordingTextAdapter(
            inner,
            self.budget_guard,
            model,
            stage,
            self.folder,
            self.clock,
            on_warning=self.on_warning,
        )

    def _record_stage_artifacts(self, stage: str, outputs: list[Path]) -> None:
        hashes = {
            path.relative_to(self.folder.root).as_posix(): _sha256_bytes_file(path)
            for path in outputs
            if path.is_file()
        }
        append_run_log(
            self.folder,
            RunLogEntry(
                timestamp=self.clock.now(),
                stage=stage,
                provider_or_agent="-",
                model="-",
                prompt_template="-",
                prompt_version="-",
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd=0.0,
                wall_time_s=0.0,
                artifact_hashes=hashes,
                event="stage_artifacts",
            ),
        )

    def _stage_is_approved(self, stage: str, path: Path) -> bool:
        """A stage is complete only when its artifact was generated *and*
        approved (T-320) — not merely present on disk. A crash between
        generation and gate approval, or an artifact edited after approval,
        both fall through to `False` and re-run the gate (or the stage)."""
        if not path.is_file():
            return False
        outcome = latest_gate_outcome(self.folder, stage)
        if outcome is None or outcome.decision == "reject":
            return False
        return outcome.artifact_hash == _sha256_text_file(path)

    def _record_gate_outcome(
        self, stage: str, *, decision: str, artifact_text: str, feedback: str | None
    ) -> None:
        record_gate_outcome(
            self.folder,
            GateOutcome(
                timestamp=self.clock.now(),
                stage=stage,
                decision=decision,
                artifact_hash=hashlib.sha256(artifact_text.encode("utf-8")).hexdigest(),
                feedback=feedback,
            ),
        )

    def _apply_gate_to_file(self, stage: str, path: Path, policy: GatePolicy) -> None:
        text = self.folder.read_text(path) or ""
        try:
            approved = apply_gate(text, policy=policy, io=self.gate_io)
        except GateRejected as exc:
            self._record_gate_outcome(
                stage, decision="reject", artifact_text=text, feedback=str(exc)
            )
            raise

        if approved != text:
            self.folder.write_text(path, approved)
        decision = "approve" if approved == text else "edit"
        self._record_gate_outcome(stage, decision=decision, artifact_text=approved, feedback=None)

    def _ensure_stage_gated(
        self,
        stage: str,
        path: Path,
        policy: GatePolicy,
        generate: Callable[[str | None], None],
    ) -> None:
        """Ensure `stage`'s artifact exists, generating it if not (T-320). If
        it is not yet approved against its *current* content — never gated,
        or edited by hand since the last approval — apply the gate directly
        to what is already on disk, without regenerating. Only a rejection
        triggers regeneration: once, with the rejection's feedback; a second
        rejection propagates and halts the run (bounded, no thrashing)."""
        if not path.exists():
            generate(None)
        if self._stage_is_approved(stage, path):
            return
        try:
            self._apply_gate_to_file(stage, path, policy)
        except GateRejected as exc:
            generate(str(exc))
            self._apply_gate_to_file(stage, path, policy)

    def _generate_concept(self, feedback: str | None) -> None:
        adapter = self._wrap_text_adapter(
            self.concept_adapter, stage="concept", model=self.config.models.concept.model
        )
        stage = ConceptStage(
            folder=self.folder,
            max_rounds=self.config.brainstorm.max_rounds,
            ask_user=self.ask_user,
            regeneration_feedback=feedback,
            prompt_version=self.config.prompts.version,
            template_dir=self.config.prompts.template_dir,
        )
        stage.run(self.folder, adapter, rendered_prompt="")
        self._record_stage_artifacts("concept", stage.outputs)

    def _generate_guidelines(self, feedback: str | None) -> None:
        adapter = self._wrap_text_adapter(
            self.guidelines_adapter, stage="guidelines", model=self.config.models.guidelines.model
        )
        stage = GuidelinesStage(
            folder=self.folder,
            clock=self.clock,
            regeneration_feedback=feedback,
            prompt_version=self.config.prompts.version,
            template_dir=self.config.prompts.template_dir,
        )
        stage.run(self.folder, adapter, rendered_prompt="")
        self._record_stage_artifacts("guidelines", stage.outputs)

    def _generate_tickets(self, feedback: str | None, frozen_version: str) -> None:
        adapter = self._wrap_text_adapter(
            self.tickets_adapter, stage="tickets", model=self.config.models.tickets.model
        )
        stage = TicketsStage(
            folder=self.folder,
            frozen_version=frozen_version,
            clock=self.clock,
            regeneration_feedback=feedback,
            prompt_version=self.config.prompts.version,
            template_dir=self.config.prompts.template_dir,
        )
        stage.run(self.folder, adapter, rendered_prompt="")
        self._record_stage_artifacts("tickets", stage.outputs)

    def _run_implement(self, frozen_version: str) -> list[str]:
        coding_adapter = _RecordingCodingAdapter(
            self.coding_adapter,
            self.config.models.implement.model,
            self.folder,
            self.clock,
            self.budget_guard,
        )
        reviewer_adapter = _RecordingReviewerAdapter(
            self.reviewer_adapter,
            self.config.models.review.model,
            self.folder,
            self.clock,
            self.budget_guard,
        )
        stage = ImplementStage(
            folder=self.folder,
            frozen_version=frozen_version,
            clock=self.clock,
            sandbox=self.sandbox,
            reviewer=reviewer_adapter,
            retry_budget=self.config.implementation.retry_budget,
            prompt_version=self.config.prompts.version,
            template_dir=self.config.prompts.template_dir,
            require_tests_green=self.config.implementation.review.require_tests_green,
            require_llm_review=self.config.implementation.review.require_llm_review,
        )
        result = stage.run(self.folder, coding_adapter, rendered_prompt="")
        return result.blocking_questions
