# T-300 — Phase boundary must stop *after* implementing the active phase, not before

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/orchestrator.py`, `tests/test_e2e_pipeline.py`,
`tests/unit/test_orchestrator.py`

## Problem
`Orchestrator.run()` checks `_should_stop_at_phase_boundary()` **before**
`_run_implement()` and halts. Any project whose concept declares phasing with
`stop_after_active_phase: true` therefore never reaches Stage 3 — the harness
produces tickets and **zero code** for phased projects. The concept says the
opposite: "the harness implements only the **active phase** and **stops** at the
phase boundary" (concept §6.3); "`phase_boundary: stop` halts **after** the
active phase" (concept §11). The e2e test
`test_phase_stop_halts_before_implementation` bakes the wrong behaviour in, so
the suite is green while the pipeline is broken for its primary phased use case.

## Goal
Implement the active phase, then halt at the phase boundary awaiting the user's
go-ahead — exactly concept §6.3/§11 semantics.

## Creates / changes
- `orchestrator.py` — move the phase-boundary check to **after**
  `_run_implement()` completes for the active phase. The halt result
  (`halted=True, halt_reason="phase_boundary"`) still returns, but `implement`
  is in `completed_stages`.
- `tests/test_e2e_pipeline.py` — replace
  `test_phase_stop_halts_before_implementation` with a test asserting the
  coding agent **was** invoked for active-phase tickets and the run then
  halted at the boundary.
- `tests/unit/test_orchestrator.py` — same correction for the unit-level test.

## Acceptance criteria
- With phasing declared (`stop_after_active_phase: true`): all active-phase
  tickets are implemented and pass their gates, **then** the run halts with
  `halt_reason="phase_boundary"`.
- Without phasing: behaviour unchanged (run to completion, no halt).
- A second run after the phase halt makes no further adapter calls for the
  completed active phase (idempotency preserved).

## Out of scope
- Activating the next phase / multi-phase progression (T-540).
- Any change to how Stage 2 scopes tickets to the active phase.

## Connections
- **Depends on:** T-220, T-240.
- **Blocks:** T-540.
- **Relates to:** T-210 (its "phase stop is structural" deviation note in
  PROGRESS.md remains correct for ticket scoping — this ticket fixes only the
  orchestrator's halt point).

## Testing
**Test-first.** Update the two wrong tests to encode the concept's semantics
before changing the orchestrator; both must fail against current behaviour.
