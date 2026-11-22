# T-310 — Actually record model/agent calls to run.log (and surface budget warnings)

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/orchestrator.py`, `src/harness/journal.py` (consumer
wiring only), `tests/unit/test_orchestrator.py`

## Problem
`journal.append_run_log()` exists and is unit-tested, but **no production code
ever calls it** — `run.log` is never written during a run. T-220's acceptance
criterion "Each model/agent call is recorded to `run.log` with template +
version + usage" is unmet, and concept §14 ("every model call's prompt, model,
token count and cost is logged") is unfulfilled: the observability and
prompt-A/B goals have no data to work with. Additionally,
`BudgetGuard.record_usage()` returns a `warned` flag that
`_BudgetTrackedTextAdapter.generate()` silently discards — the `warn_at_usd`
threshold (concept §14) never reaches the user or the journal.

## Goal
Every model/agent call in a run produces one `run.log` entry, and crossing the
budget warning threshold is visibly surfaced.

## Creates / changes
- `orchestrator.py`:
  - `_BudgetTrackedTextAdapter` (or a sibling recording wrapper) appends a
    `RunLogEntry` after each `generate()`: stage, provider, model, prompt
    template name + version, token counts, estimated cost, wall time (from the
    injected `Clock`), and content hashes of artifacts written by that stage.
  - Stage 3: append entries for each `adapter.run()` and `adapter.review()`
    call using the agent's self-reported usage/cost (see DECISIONS.md T-220 —
    recorded as-is, not routed through the rate table).
  - When `UsageResult.warned` is true, emit a visible warning (stderr echo via
    a caller-injected callback) **and** a run.log entry marking the crossing.
- Template name/version must flow to the recorder — stages currently render
  templates internally; expose what was rendered (see also T-400).

## Acceptance criteria
- A full fake-driven pipeline run leaves a `run.log` with ≥ one valid
  JSON-line per adapter call, each independently parseable (`read_run_log`).
- Entries carry template name + version and non-negative token/cost numbers.
- Crossing `warn_at_usd` produces exactly one warning event, visible to the
  caller and present in `run.log`.
- No entry is written for skipped (idempotent) stages.

## Out of scope
- Unified budget enforcement over Stage 3 spend (T-510).
- `status`/log-viewing UX (T-560).

## Connections
- **Depends on:** T-050, T-220.
- **Blocks:** T-560, prompt A/B tooling (v1).
- **Relates to:** T-060, T-510.

## Testing
**Test-first.** Fake-driven orchestrator run → assert run.log contents; warn
crossing asserted via a scripted usage sequence; skipped-stage runs append
nothing.
