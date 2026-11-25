"""Behavioural tests for the journal (T-050, T-530)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.core.clock import FrozenClock
from harness.folder import ProjectFolder
from harness.journal import (
    DecisionRecord,
    EscalationRecord,
    GateOutcome,
    ProgressEntry,
    RunLogEntry,
    append_run_log,
    calls_by_template,
    latest_escalation_for,
    latest_gate_outcome,
    read_decisions,
    read_escalations,
    read_gate_outcomes,
    read_progress,
    read_run_log,
    record_decision,
    record_escalation,
    record_gate_outcome,
    record_progress,
    resolve_escalation,
    resume_state,
    spend_by_stage,
    spend_total,
)

FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def make_run_log_entry(**overrides: object) -> RunLogEntry:
    defaults: dict[str, object] = {
        "timestamp": FIXED,
        "stage": "concept",
        "provider_or_agent": "anthropic",
        "model": "claude-opus-4-8",
        "prompt_template": "concept-write",
        "prompt_version": "v1",
        "input_tokens": 100,
        "output_tokens": 200,
        "estimated_cost_usd": 0.05,
        "wall_time_s": 1.2,
        "artifact_hashes": {"spec/concept.md": "abc123"},
    }
    defaults.update(overrides)
    return RunLogEntry.model_validate(defaults)


def test_run_log_lines_are_independently_parseable_json(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    append_run_log(folder, make_run_log_entry())
    append_run_log(folder, make_run_log_entry(stage="guidelines"))

    lines = folder.journal_run_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)  # must not raise
        assert "stage" in parsed


def test_run_log_round_trips_via_read_helper(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    append_run_log(folder, make_run_log_entry())
    append_run_log(folder, make_run_log_entry(stage="guidelines"))
    entries = read_run_log(folder)
    assert [e.stage for e in entries] == ["concept", "guidelines"]


def test_missing_run_log_reads_as_empty(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert read_run_log(folder) == []


def test_record_decision_keeps_markdown_and_json_in_sync(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    decision = DecisionRecord(
        timestamp=FIXED,
        ticket="T-180",
        conflict="guidelines suggested X; concept implies Y",
        resolution="Y (concept wins)",
        reasoning="concept outranks guidelines per precedence rule",
    )
    record_decision(folder, decision)

    json_decisions = read_decisions(folder)
    assert len(json_decisions) == 1
    assert json_decisions[0].resolution == "Y (concept wins)"

    markdown = folder.journal_decisions_md.read_text(encoding="utf-8")
    assert "T-180" in markdown
    assert "Y (concept wins)" in markdown


def test_record_progress_keeps_markdown_and_json_in_sync(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    entry = ProgressEntry(
        timestamp=FIXED,
        ticket="T-020",
        summary="Implemented Clock/IdGen/errors.",
        deviations=["none"],
    )
    record_progress(folder, entry)

    json_entries = read_progress(folder)
    assert len(json_entries) == 1
    assert json_entries[0].ticket == "T-020"

    markdown = folder.journal_progress_md.read_text(encoding="utf-8")
    assert "T-020" in markdown
    assert "Implemented Clock/IdGen/errors." in markdown


def test_progress_json_round_trips_across_multiple_entries(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-010", summary="scaffolding"))
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-020", summary="primitives"))
    entries = read_progress(folder)
    assert [e.ticket for e in entries] == ["T-010", "T-020"]


def test_resume_state_lists_completed_and_incomplete(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-010", summary="done"))
    record_progress(folder, ProgressEntry(timestamp=FIXED, ticket="T-020", summary="done"))

    state = resume_state(folder, all_units=["T-010", "T-020", "T-030", "T-040"])
    assert state.completed == ["T-010", "T-020"]
    assert state.incomplete == ["T-030", "T-040"]


def test_resume_state_on_fresh_journal_is_all_incomplete(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    state = resume_state(folder, all_units=["T-010", "T-020"])
    assert state.completed == []
    assert state.incomplete == ["T-010", "T-020"]


def test_missing_decisions_journal_reads_as_empty(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert read_decisions(folder) == []


def test_record_gate_outcome_keeps_markdown_and_json_in_sync(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    outcome = GateOutcome(
        timestamp=FIXED, stage="concept", decision="approve", artifact_hash="abc123"
    )
    record_gate_outcome(folder, outcome)

    outcomes = read_gate_outcomes(folder)
    assert len(outcomes) == 1
    assert outcomes[0].decision == "approve"

    markdown = folder.journal_gates_md.read_text(encoding="utf-8")
    assert "concept" in markdown
    assert "abc123" in markdown


def test_latest_gate_outcome_returns_the_most_recent_for_a_stage(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_gate_outcome(
        folder,
        GateOutcome(timestamp=FIXED, stage="concept", decision="reject", artifact_hash="h1"),
    )
    record_gate_outcome(
        folder,
        GateOutcome(timestamp=FIXED, stage="concept", decision="approve", artifact_hash="h2"),
    )
    record_gate_outcome(
        folder,
        GateOutcome(timestamp=FIXED, stage="guidelines", decision="approve", artifact_hash="h3"),
    )

    latest = latest_gate_outcome(folder, "concept")
    assert latest is not None
    assert latest.decision == "approve"
    assert latest.artifact_hash == "h2"


def test_latest_gate_outcome_is_none_for_an_ungated_stage(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert latest_gate_outcome(folder, "concept") is None


def test_timestamps_come_from_injected_clock_in_caller_code(tmp_path: Path) -> None:
    # journal.py itself takes pre-built entries (timestamp already set by the
    # caller's injected Clock); this proves the round trip preserves it exactly.
    clock = FrozenClock(FIXED)
    folder = ProjectFolder(tmp_path)
    entry = ProgressEntry(timestamp=clock.now(), ticket="T-050", summary="journal")
    record_progress(folder, entry)
    assert read_progress(folder)[0].timestamp == FIXED


def test_record_escalation_keeps_markdown_and_json_in_sync(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="failed 3 times"
        ),
    )

    escalations = read_escalations(folder)
    assert len(escalations) == 1
    assert escalations[0].resolution is None

    markdown = folder.journal_escalations_md.read_text(encoding="utf-8")
    assert "T-010" in markdown
    assert "failed 3 times" in markdown


def test_latest_escalation_for_returns_the_most_recent(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="a"),
    )
    record_escalation(
        folder,
        EscalationRecord(timestamp=FIXED, kind="retry_exhausted", ticket="T-020", context="b"),
    )

    assert latest_escalation_for(folder, "T-010").context == "a"  # type: ignore[union-attr]
    assert latest_escalation_for(folder, "T-020").context == "b"  # type: ignore[union-attr]
    assert latest_escalation_for(folder, "T-030") is None


def test_resolve_escalation_appends_a_resolved_record(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(
            timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="failed 3 times"
        ),
    )

    resolve_escalation(folder, "T-010", "use library X instead", FIXED)

    latest = latest_escalation_for(folder, "T-010")
    assert latest is not None
    assert latest.resolution == "use library X instead"
    assert len(read_escalations(folder)) == 2  # original + resolution, both kept


def test_resolve_escalation_raises_when_nothing_is_open(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    with pytest.raises(ValueError, match="no open escalation"):
        resolve_escalation(folder, "T-010", "an answer", FIXED)


def test_resolve_escalation_raises_when_already_resolved(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_escalation(
        folder,
        EscalationRecord(timestamp=FIXED, kind="retry_exhausted", ticket="T-010", context="x"),
    )
    resolve_escalation(folder, "T-010", "first answer", FIXED)

    with pytest.raises(ValueError, match="no open escalation"):
        resolve_escalation(folder, "T-010", "second answer", FIXED)


def test_run_level_escalation_uses_none_as_the_ticket_key(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    record_escalation(
        folder, EscalationRecord(timestamp=FIXED, kind="drift", ticket=None, context="found drift")
    )
    latest = latest_escalation_for(folder, None)
    assert latest is not None
    assert latest.kind == "drift"


def test_spend_total_sums_estimated_cost_across_entries() -> None:
    entries = [
        make_run_log_entry(estimated_cost_usd=0.05),
        make_run_log_entry(estimated_cost_usd=0.10),
        make_run_log_entry(stage="guidelines", estimated_cost_usd=0.02),
    ]
    assert spend_total(entries) == pytest.approx(0.17)


def test_spend_total_on_an_empty_run_log_is_zero() -> None:
    assert spend_total([]) == 0.0


def test_spend_by_stage_groups_cost_per_stage() -> None:
    entries = [
        make_run_log_entry(stage="concept", estimated_cost_usd=0.05),
        make_run_log_entry(stage="concept", estimated_cost_usd=0.03),
        make_run_log_entry(stage="guidelines", estimated_cost_usd=0.10),
    ]
    totals = spend_by_stage(entries)
    assert totals == {"concept": pytest.approx(0.08), "guidelines": pytest.approx(0.10)}


def test_calls_by_template_groups_by_template_and_version() -> None:
    entries = [
        make_run_log_entry(
            prompt_template="concept-write",
            prompt_version="v1",
            input_tokens=100,
            output_tokens=200,
            estimated_cost_usd=0.05,
        ),
        make_run_log_entry(
            prompt_template="concept-write",
            prompt_version="v1",
            input_tokens=50,
            output_tokens=100,
            estimated_cost_usd=0.02,
        ),
        make_run_log_entry(
            prompt_template="concept-write",
            prompt_version="v2",
            input_tokens=80,
            output_tokens=90,
            estimated_cost_usd=0.04,
        ),
    ]
    grouped = calls_by_template(entries)

    v1_stats = grouped[("concept-write", "v1")]
    assert v1_stats.calls == 2
    assert v1_stats.input_tokens == 150
    assert v1_stats.output_tokens == 300
    assert v1_stats.cost_usd == pytest.approx(0.07)

    v2_stats = grouped[("concept-write", "v2")]
    assert v2_stats.calls == 1
    assert v2_stats.input_tokens == 80


def test_calls_by_template_on_an_empty_run_log_is_empty() -> None:
    assert calls_by_template([]) == {}
