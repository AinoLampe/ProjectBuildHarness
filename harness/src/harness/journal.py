"""run.log (JSON-lines) + DECISIONS/PROGRESS markdown with JSON mirrors
(concept §10.5, §14). Timestamps are always supplied by the caller's injected
`Clock`; this module never reads the wall clock itself."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from harness.folder import ProjectFolder


class RunLogEntry(BaseModel):
    """One model/agent call: stage, provider/agent, model, prompt identity,
    token usage, estimated cost, wall time, and output artifact hashes.

    `event` is `None` for an ordinary adapter call. Synthetic bookkeeping
    entries (a stage's artifact hashes recorded after it finishes writing, or
    a budget-warning crossing) set it to a short label (e.g.
    `"stage_artifacts"`, `"budget_warning"`) and use zero/placeholder values
    for the fields that don't apply (T-310)."""

    timestamp: datetime
    stage: str
    provider_or_agent: str
    model: str
    prompt_template: str
    prompt_version: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    wall_time_s: float
    artifact_hashes: dict[str, str] = {}
    event: str | None = None


class DecisionRecord(BaseModel):
    """A conflict or ambiguity resolution (concept-wins precedence or an
    escalation), recorded for human audit and orchestrator reasoning."""

    timestamp: datetime
    ticket: str | None = None
    conflict: str
    resolution: str
    reasoning: str


class ProgressEntry(BaseModel):
    """One completed unit of work: ticket id, summary, and any deviations.

    `frozen_version` records which frozen spec snapshot the work was done
    against (T-330); `None` for entries recorded before this field existed.
    An upstream re-freeze invalidates completed-ness for a *different*
    frozen_version — see `resume_state(..., frozen_version=...)`."""

    timestamp: datetime
    ticket: str
    summary: str
    deviations: list[str] = []
    frozen_version: str | None = None


class ResumeState(BaseModel):
    """Which declared units are already done vs. still outstanding."""

    completed: list[str]
    incomplete: list[str]


class GateOutcome(BaseModel):
    """The result of applying a gate to one stage's artifact (T-320):
    which stage, what the user decided, a content hash of the artifact the
    decision applies to (so a later edit invalidates the recorded approval),
    and — for a rejection — the feedback that must drive regeneration."""

    timestamp: datetime
    stage: str
    decision: str
    artifact_hash: str
    feedback: str | None = None


def append_run_log(folder: ProjectFolder, entry: RunLogEntry) -> None:
    folder.append_text(folder.journal_run_log, entry.model_dump_json() + "\n")


def read_run_log(folder: ProjectFolder) -> list[RunLogEntry]:
    text = folder.read_text(folder.journal_run_log, required=False)
    if not text:
        return []
    return [RunLogEntry.model_validate_json(line) for line in text.splitlines() if line.strip()]


def spend_total(entries: list[RunLogEntry]) -> float:
    """Sum of `estimated_cost_usd` across `entries` (T-560) — `0.0` for an
    empty/missing run.log, not an error."""
    return sum(entry.estimated_cost_usd for entry in entries)


def spend_by_stage(entries: list[RunLogEntry]) -> dict[str, float]:
    """Spend total grouped by `stage`, in first-seen order (T-560)."""
    totals: dict[str, float] = {}
    for entry in entries:
        totals[entry.stage] = totals.get(entry.stage, 0.0) + entry.estimated_cost_usd
    return totals


@dataclass(frozen=True)
class TemplateStats:
    """Aggregate call count, token usage, and spend for one (template,
    version) pair — the primitive prompt A/B comparison is built on
    (T-560)."""

    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


def calls_by_template(entries: list[RunLogEntry]) -> dict[tuple[str, str], TemplateStats]:
    """Group `entries` by `(prompt_template, prompt_version)`, in first-seen
    order (T-560) — the same template used across two prompt versions
    produces two separate keys, so a caller can compare them directly."""
    grouped: dict[tuple[str, str], TemplateStats] = {}
    for entry in entries:
        key = (entry.prompt_template, entry.prompt_version)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = TemplateStats(
                calls=1,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                cost_usd=entry.estimated_cost_usd,
            )
        else:
            grouped[key] = TemplateStats(
                calls=existing.calls + 1,
                input_tokens=existing.input_tokens + entry.input_tokens,
                output_tokens=existing.output_tokens + entry.output_tokens,
                cost_usd=existing.cost_usd + entry.estimated_cost_usd,
            )
    return grouped


def record_decision(folder: ProjectFolder, decision: DecisionRecord) -> None:
    decisions = read_decisions(folder)
    decisions.append(decision)
    folder.write_json_atomic(
        folder.journal_decisions_json, [d.model_dump(mode="json") for d in decisions]
    )

    heading = f"## {decision.timestamp.isoformat()} — {decision.ticket or 'unscoped'}"
    block = (
        f"{heading}\n"
        f"- **Conflict:** {decision.conflict}\n"
        f"- **Resolution:** {decision.resolution}\n"
        f"- **Reasoning:** {decision.reasoning}\n\n"
    )
    if not folder.journal_decisions_md.exists():
        folder.append_text(folder.journal_decisions_md, "# Decisions\n\n")
    folder.append_text(folder.journal_decisions_md, block)


def read_decisions(folder: ProjectFolder) -> list[DecisionRecord]:
    raw = folder.read_json(folder.journal_decisions_json, required=False)
    if not raw:
        return []
    return [DecisionRecord.model_validate(item) for item in raw]


def record_progress(folder: ProjectFolder, entry: ProgressEntry) -> None:
    entries = read_progress(folder)
    entries.append(entry)
    folder.write_json_atomic(
        folder.journal_progress_json, [e.model_dump(mode="json") for e in entries]
    )

    deviations = "; ".join(entry.deviations) if entry.deviations else "none"
    block = (
        f"## {entry.ticket} — {entry.timestamp.isoformat()}\n"
        f"{entry.summary}\n\n"
        f"Deviations: {deviations}\n\n"
    )
    if not folder.journal_progress_md.exists():
        folder.append_text(folder.journal_progress_md, "# Progress\n\n")
    folder.append_text(folder.journal_progress_md, block)


def read_progress(folder: ProjectFolder) -> list[ProgressEntry]:
    raw = folder.read_json(folder.journal_progress_json, required=False)
    if not raw:
        return []
    return [ProgressEntry.model_validate(item) for item in raw]


def record_gate_outcome(folder: ProjectFolder, outcome: GateOutcome) -> None:
    outcomes = read_gate_outcomes(folder)
    outcomes.append(outcome)
    folder.write_json_atomic(
        folder.journal_gates_json, [o.model_dump(mode="json") for o in outcomes]
    )

    block = (
        f"## {outcome.stage} — {outcome.timestamp.isoformat()}\n"
        f"Decision: {outcome.decision}\n"
        f"Artifact hash: {outcome.artifact_hash}\n"
        f"Feedback: {outcome.feedback or 'none'}\n\n"
    )
    if not folder.journal_gates_md.exists():
        folder.append_text(folder.journal_gates_md, "# Gates\n\n")
    folder.append_text(folder.journal_gates_md, block)


def read_gate_outcomes(folder: ProjectFolder) -> list[GateOutcome]:
    raw = folder.read_json(folder.journal_gates_json, required=False)
    if not raw:
        return []
    return [GateOutcome.model_validate(item) for item in raw]


def latest_gate_outcome(folder: ProjectFolder, stage: str) -> GateOutcome | None:
    """The most recent gate outcome recorded for `stage`, or `None` if the
    stage has never been gated."""
    matching = [o for o in read_gate_outcomes(folder) if o.stage == stage]
    return matching[-1] if matching else None


class EscalationRecord(BaseModel):
    """A run that cannot proceed without human input (T-530): retry-budget
    exhaustion, unresolved ambiguity, final-acceptance drift, or a budget
    halt. `ticket` is `None` for a run-level escalation (e.g. drift, which
    isn't about one ticket). Like `GateOutcome`, this is append-only:
    "resolving" an escalation appends a *new* record for the same
    `(kind, ticket)` with `resolution` filled in; `latest_escalation_for`
    always reflects the newest state."""

    timestamp: datetime
    kind: str
    ticket: str | None
    context: str
    resolution: str | None = None


def record_escalation(folder: ProjectFolder, record: EscalationRecord) -> None:
    records = read_escalations(folder)
    records.append(record)
    folder.write_json_atomic(
        folder.journal_escalations_json, [r.model_dump(mode="json") for r in records]
    )

    block = (
        f"## {record.kind} — {record.ticket or 'run'} — {record.timestamp.isoformat()}\n"
        f"{record.context}\n\n"
        f"Resolution: {record.resolution or '(open — use `harness resolve` to answer it)'}\n\n"
    )
    if not folder.journal_escalations_md.exists():
        folder.append_text(folder.journal_escalations_md, "# Escalations\n\n")
    folder.append_text(folder.journal_escalations_md, block)


def read_escalations(folder: ProjectFolder) -> list[EscalationRecord]:
    raw = folder.read_json(folder.journal_escalations_json, required=False)
    if not raw:
        return []
    return [EscalationRecord.model_validate(item) for item in raw]


def latest_escalation_for(folder: ProjectFolder, ticket: str | None) -> EscalationRecord | None:
    """The most recent escalation for `ticket` (or the most recent
    run-level escalation, if `ticket` is `None`) — `None` if there has
    never been one. Check `.resolution is None` to see if it's still open."""
    matching = [r for r in read_escalations(folder) if r.ticket == ticket]
    return matching[-1] if matching else None


def resolve_escalation(
    folder: ProjectFolder, ticket: str | None, answer: str, now: datetime
) -> None:
    """Answer the open escalation for `ticket` (`harness resolve`, T-530):
    appends a new record carrying the same `kind`/`context` with
    `resolution` filled in, so `latest_escalation_for` reports it as
    closed. Raises `ValueError` if there is no open escalation to answer —
    resolving nothing would silently do nothing useful."""
    open_escalation = latest_escalation_for(folder, ticket)
    if open_escalation is None or open_escalation.resolution is not None:
        raise ValueError(f"no open escalation for {ticket or 'the run'!r} to resolve")
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=now,
            kind=open_escalation.kind,
            ticket=ticket,
            context=open_escalation.context,
            resolution=answer,
        ),
    )


def resume_state(
    folder: ProjectFolder, all_units: list[str], *, frozen_version: str | None = None
) -> ResumeState:
    """Reconstruct resume state: which of `all_units` already have a
    `progress.json` entry, and which (in declared order) do not.

    When `frozen_version` is given, an entry only counts as done if it was
    recorded against that exact frozen version (T-330) — a progress entry
    left over from a since-invalidated spec must not be treated as
    completed. Entries with no recorded `frozen_version` (pre-T-330) count
    as done regardless, preserving old journals' resumability."""
    done = {
        entry.ticket
        for entry in read_progress(folder)
        if frozen_version is None
        or entry.frozen_version is None
        or entry.frozen_version == frozen_version
    }
    completed = [unit for unit in all_units if unit in done]
    incomplete = [unit for unit in all_units if unit not in done]
    return ResumeState(completed=completed, incomplete=incomplete)
