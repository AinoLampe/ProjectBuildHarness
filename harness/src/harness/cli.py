"""Typer CLI entry points (concept §17): `run`, `status`, `gate`. Wires the
orchestrator (T-220) and config (T-030); `status` reads the journal (T-050);
`gate` drives a gate decision (T-150) directly against the folder.
"""

import hashlib
from pathlib import Path
from typing import cast

import typer
import yaml

from harness.adapters.anthropic_text import DEFAULT_MAX_TOKENS, AnthropicTextAdapter
from harness.adapters.claude_code import ClaudeCodeAdapter
from harness.budget import RATE_TABLE, BudgetGuard, ModelRate
from harness.config import HarnessConfig, ModelRoute, load_config
from harness.core.clock import Clock, SystemClock
from harness.core.errors import GateRejected
from harness.folder import ProjectFolder
from harness.freeze import latest_version
from harness.gates import GateResponse, apply_gate
from harness.journal import (
    GateOutcome,
    latest_gate_outcome,
    read_decisions,
    read_escalations,
    read_progress,
    read_run_log,
    record_gate_outcome,
    resolve_escalation,
    spend_by_stage,
    spend_total,
)
from harness.orchestrator import Orchestrator
from harness.sandbox import Sandbox
from harness.stages.implement import parse_ticket_file

app = typer.Typer(help="AI harness for project initialisation.")

_STAGE_ARTIFACTS = ("concept", "guidelines", "tickets", "implement")


def _interactive_gate_io(artifact: str) -> GateResponse:
    typer.echo(artifact)
    decision = typer.prompt("approve / edit / reject").strip().lower()
    if decision == "approve":
        return GateResponse(decision="approve")
    if decision == "edit":
        edited = typer.prompt("enter the replacement content")
        return GateResponse(decision="edit", edited_artifact=edited)
    if decision == "reject":
        feedback = typer.prompt("feedback")
        return GateResponse(decision="reject", feedback=feedback)
    return GateResponse(decision="reject", feedback=f"unrecognised gate decision: {decision!r}")


def _interactive_ask_user(question: str) -> str:
    typer.echo(question)
    return typer.prompt("> ")


def _merged_rate_table(config: HarnessConfig) -> dict[str, ModelRate]:
    """`budget.model_rates` overrides/extends `RATE_TABLE`'s defaults
    (T-370)."""
    merged = dict(RATE_TABLE)
    for model, rate in config.budget.model_rates.items():
        merged[model] = ModelRate(
            input_per_mtok_usd=rate.input_per_mtok_usd, output_per_mtok_usd=rate.output_per_mtok_usd
        )
    return merged


def _from_route(route: ModelRoute) -> AnthropicTextAdapter:
    return AnthropicTextAdapter.from_api_key(route.model, route.max_tokens or DEFAULT_MAX_TOKENS)


def build_orchestrator(folder: ProjectFolder, config: HarnessConfig, clock: Clock) -> Orchestrator:
    """Build a real, single-provider (v0) orchestrator from config. Tests
    monkeypatch this function to inject fakes instead."""
    concept_adapter = _from_route(config.models.concept)
    guidelines_adapter = _from_route(config.models.guidelines)
    tickets_adapter = _from_route(config.models.tickets)
    sandbox = Sandbox(
        root=folder.root,
        network=config.sandbox.network,
        container_image=config.sandbox.container_image,
        ephemeral=config.sandbox.ephemeral,
        default_timeout_s=config.sandbox.command_timeout_s,
    )
    coding_adapter = ClaudeCodeAdapter(
        project_root=folder.root,
        implement_model=config.models.implement.model,
        review_model=config.models.review.model,
        command_timeout_s=config.implementation.agent_timeout_s,
    )
    budget_guard = BudgetGuard(
        max_usd_per_run=config.budget.max_usd_per_run,
        warn_at_usd=config.budget.warn_at_usd,
        rate_table=_merged_rate_table(config),
    )
    return Orchestrator(
        folder=folder,
        config=config,
        clock=clock,
        concept_adapter=concept_adapter,
        guidelines_adapter=guidelines_adapter,
        tickets_adapter=tickets_adapter,
        coding_adapter=coding_adapter,
        reviewer_adapter=coding_adapter,
        sandbox=sandbox,
        gate_io=_interactive_gate_io,
        ask_user=_interactive_ask_user,
        budget_guard=budget_guard,
        on_warning=lambda message: typer.echo(message, err=True),
    )


@app.command()
def run(
    project: Path = typer.Option(..., "--project", help="Project folder root."),
    from_stage: str | None = typer.Option(
        None, "--from", help=f"Resume from one of: {', '.join(_STAGE_ARTIFACTS)}."
    ),
) -> None:
    """Run the full pipeline (or resume — the orchestrator is idempotent).
    `--from <stage>` forces regeneration from that stage onward, moving its
    current artifacts aside rather than discarding them (T-330)."""
    if from_stage is not None and from_stage not in _STAGE_ARTIFACTS:
        typer.echo(f"--from must be one of: {', '.join(_STAGE_ARTIFACTS)}", err=True)
        raise typer.Exit(code=1)

    folder = ProjectFolder(project)
    config = load_config(folder.harness_config_yaml)
    orchestrator = build_orchestrator(folder, config, SystemClock())
    if from_stage is not None:
        orchestrator.invalidate_from(from_stage)
    result = orchestrator.run()

    typer.echo(f"Completed stages: {', '.join(result.completed_stages)}")

    if result.halted and result.halt_reason == "escalation":
        typer.echo("Escalated — this run needs human input before it can continue:")
        for warning in result.warnings:
            typer.echo(f"  - {warning}")
        typer.echo(
            "Run `harness status --project <dir>` to see open escalations, then "
            "`harness resolve --project <dir> --ticket <id> --answer ...` to answer one."
        )
        raise typer.Exit(code=5)

    if result.warnings:
        typer.echo("Warnings (final acceptance pass found drift from the original requirements):")
        for warning in result.warnings:
            typer.echo(f"  - {warning}")

    if result.halted:
        typer.echo(f"Halted: {result.halt_reason}")
        if result.halt_reason == "phase_boundary":
            typer.echo(
                "The active phase is implemented. Run `harness phase --project "
                f"{project} --next` to activate the next phase, or `--activate <id>` "
                "for a specific one (T-540)."
            )
        raise typer.Exit(code=2)

    if result.warnings:
        raise typer.Exit(code=4)


@app.command()
def status(project: Path = typer.Option(..., "--project", help="Project folder root.")) -> None:
    """Print pipeline position, spend, open escalations, and progress
    (T-560) — what an unattended-run operator needs to know: what this is
    costing, and where it's stuck. Open escalations are shown first —
    they're what's blocking the next `harness run` (T-530)."""
    folder = ProjectFolder(project)
    config = load_config(folder.harness_config_yaml)
    escalations = read_escalations(folder)
    open_escalations = [e for e in escalations if e.resolution is None]
    progress = read_progress(folder)
    decisions = read_decisions(folder)
    run_log = read_run_log(folder)

    if open_escalations:
        typer.echo(f"Open escalations: {len(open_escalations)} (resolve these before re-running)")
        for escalation in open_escalations:
            typer.echo(
                f"  - [{escalation.kind}] {escalation.ticket or 'run'}: {escalation.context}"
            )
        typer.echo()

    frozen_version = latest_version(folder)
    typer.echo(f"Frozen spec version: {frozen_version or '(none frozen yet)'}")
    typer.echo("Pipeline:")
    for stage in _STAGE_ARTIFACTS[:-1]:  # concept, guidelines, tickets — gated stages
        outcome = latest_gate_outcome(folder, stage)
        typer.echo(f"  - {stage}: {outcome.decision if outcome is not None else 'pending'}")
    typer.echo(f"  - implement: {'done' if progress else 'pending'} ({len(progress)} ticket(s))")
    typer.echo()

    if not run_log:
        typer.echo("Spend: no runs recorded")
    else:
        total_spend = spend_total(run_log)
        cap = config.budget.max_usd_per_run
        over_warn = " (over warn threshold)" if total_spend >= config.budget.warn_at_usd else ""
        typer.echo(f"Spend: ${total_spend:.4f} / ${cap:.4f} cap{over_warn}")
        for stage, cost in spend_by_stage(run_log).items():
            typer.echo(f"  - {stage}: ${cost:.4f}")
    typer.echo()

    typer.echo(f"Progress: {len(progress)} entries")
    for entry in progress:
        typer.echo(f"  - {entry.ticket}: {entry.summary}")

    typer.echo(f"Decisions: {len(decisions)} entries")
    for decision in decisions:
        typer.echo(f"  - {decision.ticket or 'unscoped'}: {decision.resolution}")


@app.command(name="log")
def log_command(
    project: Path = typer.Option(..., "--project", help="Project folder root."),
    tail: int | None = typer.Option(None, "--tail", help="Show only the last N entries."),
    stage: str | None = typer.Option(None, "--stage", help="Filter to one stage."),
) -> None:
    """Pretty-print run.log entries (T-560) — timestamp, stage, model,
    template@version, tokens, and cost — without parsing JSON lines by
    hand."""
    folder = ProjectFolder(project)
    entries = read_run_log(folder)
    if stage is not None:
        entries = [e for e in entries if e.stage == stage]
    if not entries:
        typer.echo("no runs recorded")
        return
    if tail is not None:
        entries = entries[-tail:]
    for entry in entries:
        typer.echo(
            f"{entry.timestamp.isoformat()} [{entry.stage}] {entry.model} "
            f"{entry.prompt_template}@{entry.prompt_version} "
            f"tokens={entry.input_tokens}/{entry.output_tokens} "
            f"cost=${entry.estimated_cost_usd:.4f}"
        )


@app.command()
def resolve(
    project: Path = typer.Option(..., "--project", help="Project folder root."),
    ticket: str | None = typer.Option(
        None, "--ticket", help="Ticket id (e.g. T-010), or omit for a run-level escalation."
    ),
    answer: str = typer.Option(..., "--answer", help="The human's answer/decision."),
) -> None:
    """Answer an open escalation (T-530) so the next `harness run` retries
    the affected ticket with the answer folded in and a fresh retry budget,
    instead of refusing to touch it again."""
    folder = ProjectFolder(project)
    try:
        resolve_escalation(folder, ticket, answer, SystemClock().now())
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Resolved the escalation for {ticket or 'the run'}. Run `harness run` to retry.")


@app.command()
def gate(
    project: Path = typer.Option(..., "--project", help="Project folder root."),
    stage: str = typer.Option(..., help=f"One of: {', '.join(_STAGE_ARTIFACTS[:-1])}."),
    approve: bool = typer.Option(False, "--approve"),
    edit: Path | None = typer.Option(None, "--edit", help="Path to replacement content."),
    reject: str | None = typer.Option(None, "--reject", help="Rejection feedback."),
) -> None:
    """Apply approve / edit / reject to the named stage's primary artifact."""
    folder = ProjectFolder(project)
    artifact_paths = {
        "concept": folder.spec_concept_md,
        "guidelines": folder.spec_guidelines_md,
        "tickets": folder.spec_tickets_dir / "000-overview.md",
    }
    if stage not in artifact_paths:
        typer.echo(f"--stage must be one of: {', '.join(artifact_paths)}", err=True)
        raise typer.Exit(code=1)

    chosen = [flag for flag in (approve, edit is not None, reject is not None) if flag]
    if len(chosen) != 1:
        typer.echo("specify exactly one of --approve, --edit, --reject", err=True)
        raise typer.Exit(code=1)

    if approve:
        response = GateResponse(decision="approve")
    elif edit is not None:
        response = GateResponse(decision="edit", edited_artifact=edit.read_text(encoding="utf-8"))
    else:
        response = GateResponse(decision="reject", feedback=reject)

    path = artifact_paths[stage]
    text = folder.read_text(path) or ""
    try:
        approved = apply_gate(text, policy="interactive", io=lambda _artifact: response)
    except GateRejected as exc:
        record_gate_outcome(
            folder,
            GateOutcome(
                timestamp=SystemClock().now(),
                stage=stage,
                decision="reject",
                artifact_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                feedback=str(exc),
            ),
        )
        typer.echo(f"Rejected: {exc}")
        typer.echo("The next `harness run` will regenerate this stage with your feedback.")
        raise typer.Exit(code=3) from exc

    if approved != text:
        folder.write_text(path, approved)
    record_gate_outcome(
        folder,
        GateOutcome(
            timestamp=SystemClock().now(),
            stage=stage,
            decision="edit" if approved != text else "approve",
            artifact_hash=hashlib.sha256(approved.encode("utf-8")).hexdigest(),
            feedback=None,
        ),
    )
    typer.echo(f"Gate for {stage}: approved.")


@app.command(name="phase")
def phase_command(
    project: Path = typer.Option(..., "--project", help="Project folder root."),
    next_: bool = typer.Option(False, "--next", help="Activate the next declared phase."),
    activate: str | None = typer.Option(None, "--activate", help="Activate a specific phase id."),
) -> None:
    """Activate the next declared phase (T-540, concept §9.4): refuses
    unless the current phase's tickets are all complete and there are no
    open escalations, then flips `phasing.yaml` and promotes that phase's
    deferred tickets from `spec/tickets/deferred/<id>/` into
    `spec/tickets/` so the next `harness run` implements them."""
    if next_ == (activate is not None):
        typer.echo("specify exactly one of --next or --activate <id>", err=True)
        raise typer.Exit(code=1)

    folder = ProjectFolder(project)
    phasing_text = folder.read_text(folder.spec_phasing_yaml, required=False)
    if not phasing_text:
        typer.echo("no phasing declared for this project (spec/phasing.yaml is empty)", err=True)
        raise typer.Exit(code=1)

    loaded = cast("dict[str, object]", yaml.safe_load(phasing_text) or {})
    phases = cast("list[dict[str, object]]", loaded.get("phases") or [])
    if not phases:
        typer.echo("phasing.yaml declares no phases", err=True)
        raise typer.Exit(code=1)

    active_phase = next((p for p in phases if p.get("active") is True), None)
    if active_phase is not None:
        ticket_paths = sorted(
            p for p in folder.spec_tickets_dir.glob("*.md") if p.name != "000-overview.md"
        )
        ticket_ids = [parse_ticket_file(p, folder.read_text(p) or "").id for p in ticket_paths]
        done_ids = {entry.ticket for entry in read_progress(folder)}
        incomplete = [tid for tid in ticket_ids if tid not in done_ids]
        if incomplete:
            typer.echo(
                f"the active phase {active_phase.get('id')!r} is not complete yet "
                f"(pending: {', '.join(incomplete)})",
                err=True,
            )
            raise typer.Exit(code=1)

    open_escalations = [e for e in read_escalations(folder) if e.resolution is None]
    if open_escalations:
        typer.echo("resolve open escalations before activating the next phase:", err=True)
        for escalation in open_escalations:
            typer.echo(f"  - [{escalation.kind}] {escalation.ticket or 'run'}", err=True)
        raise typer.Exit(code=1)

    if activate is not None:
        target = next((p for p in phases if p.get("id") == activate), None)
    else:
        current_index = phases.index(active_phase) if active_phase is not None else -1
        target = phases[current_index + 1] if current_index + 1 < len(phases) else None

    if target is None:
        typer.echo("no phase to activate", err=True)
        raise typer.Exit(code=1)

    for candidate in phases:
        candidate["active"] = candidate is target
    loaded["phases"] = phases
    folder.write_text(folder.spec_phasing_yaml, yaml.safe_dump(loaded, sort_keys=False))

    target_id = str(target.get("id"))
    deferred_dir = folder.spec_tickets_deferred_phase_dir(target_id)
    promoted: list[str] = []
    if deferred_dir.is_dir():
        for ticket_path in sorted(deferred_dir.glob("*.md")):
            destination = folder.spec_tickets_dir / ticket_path.name
            ticket_path.rename(destination)
            promoted.append(ticket_path.name)

    typer.echo(f"Activated phase {target_id!r}.")
    typer.echo(f"Promoted tickets: {', '.join(promoted) if promoted else '(none found)'}")
    typer.echo("Run `harness run` to implement them.")
