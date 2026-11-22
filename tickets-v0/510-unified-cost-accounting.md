# T-510 — Unified cost accounting: bring Stage 3 spend under the budget cap

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/budget.py`, `src/harness/stages/implement.py`,
`src/harness/orchestrator.py`

## Motivation
DECISIONS.md (T-220) deliberately scoped `BudgetGuard` to the text adapters
and flagged unification as future work. The consequence today: the single most
expensive part of a run — the implementation stage, with its per-ticket agent
calls, retries, and per-ticket reviewer calls — is **entirely outside the
budget cap**. `budget.max_usd_per_run: 25` is a promise the harness only keeps
for the cheap stages; a thrashing retry loop in Stage 3 can spend arbitrarily.
Concept §14: "a per-run budget guard can halt the pipeline" — it must include
the agent.

The accounting split identified in that decision is real (rate-table
estimation vs. the agent's self-reported cost) and the answer is to record
both *kinds* against one ledger, not to double-account.

## Creates / changes
- `budget.py` — `BudgetGuard.record_direct_cost(source: str, cost_usd:
  float) -> UsageResult`: adds an agent-reported dollar amount to the same
  cumulative total, with the same pre-emptive projection check and warn-once
  semantics. (Depends on T-340 so the reported cost is real, not 0.0.)
- `implement.py` — after each `adapter.run()` / reviewer call, record
  `AgentResult.cost_usd` (and reviewer cost) via an injected guard;
  `BudgetExceeded` propagates like any stage failure → run halts between
  tickets, progress journal intact, resume works after the user raises the
  cap.
- `orchestrator.py` — pass its `BudgetGuard` into `ImplementStage`; halt
  reason distinguishes budget from other halts.
- Headroom for agent calls: before dispatching a ticket, require a
  configurable minimum remaining budget (`implementation.min_headroom_usd`,
  default derived from observed per-ticket cost so far) — a cheap guard
  against starting a ticket the budget cannot finish.

## Acceptance criteria
- A fake agent reporting costs that cross the cap halts the run **between
  tickets** with `BudgetExceeded`; completed tickets remain journaled; a
  re-run with a raised cap resumes at the first unfinished ticket.
- Text-stage and agent spend accumulate in one total (asserted across a full
  fake pipeline run).
- Warn-once fires on whichever call crosses `warn_at_usd`, text or agent.
- No double-accounting: an agent call's cost is recorded exactly once, via
  `record_direct_cost`, never also via the rate table.

## Out of scope
- Live pricing verification (documented run-time step, unchanged).
- Per-stage budget sub-caps (possible v1 refinement).

## Connections
- **Depends on:** T-060, T-210, T-220, T-340, T-370.
- **Blocks:** none.
- **Relates to:** T-310 (the same numbers flow to run.log).

## Testing
**Test-first.** Cases: cross-cap halt between tickets + resume; single-ledger
accumulation; warn crossing from the agent side; once-only recording.
