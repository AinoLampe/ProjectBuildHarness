# T-060 — Budget guard

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/budget.py`

## Goal
Track cumulative spend across a run, warn at a threshold, and halt before the cap
is exceeded, so a multi-stage, multi-model pipeline can run unattended without
runaway cost (concept §14).

## Creates / changes
- `budget.py` — pure cost accounting:
  - accumulate spend from adapter usage results (token counts × model rate).
  - a model-rate table, with a clear note that pricing must be verified at run
    time (concept §1 — the autonomous-usage billing model changed mid-2026).
  - `warn_at_usd` crossing → a warning signal/event.
  - `max_usd_per_run` → raise `BudgetExceeded` **before** the cap is exceeded,
    not after.

## Acceptance criteria
- Accumulation is correct across multiple calls.
- The warn signal fires exactly once when crossing `warn_at_usd`.
- `BudgetExceeded` is raised pre-emptively (the projected next call would breach
  the cap), never after overspending.
- Module is pure: no IO, no clock, no logging (the orchestrator routes events to
  the journal).
- Cost estimation from token counts + model rates is unit-tested against the
  rate table.

## Out of scope
- Writing to `run.log` (orchestrator wires budget + journal together).
- Live pricing fetch (left as a documented run-time verification step).

## Connections
- **Depends on:** T-020.
- **Blocks:** T-220.
- **Relates to:** T-050 (journal), T-100/T-130 (usage in adapter results).

## Testing
**Test-first.** Cases: accumulation; warn-once; pre-emptive halt; estimation per
rate table; the "budget exceeded mid-run" edge case from guidelines §4.4.
