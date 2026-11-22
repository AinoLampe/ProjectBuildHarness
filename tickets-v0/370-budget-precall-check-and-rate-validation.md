# T-370 — Budget: check headroom *before* the call, validate rates at config load

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/budget.py`, `src/harness/orchestrator.py`,
`src/harness/config.py`

## Problem
1. **The "pre-emptive" halt happens after the money is spent.**
   `BudgetGuard.record_usage()` is only called from
   `_BudgetTrackedTextAdapter.generate()` **after** `inner.generate()` has
   returned — i.e. after the provider call was made and paid for. The guard's
   own accounting is pre-emptive (it refuses to *record* the overspend), but
   the run has already breached the cap at the provider. T-060's criterion
   "never after overspending" only holds for the *ledger*, not the *wallet*.
2. **Unknown model = mid-run crash.** `estimate_cost_usd()` raises
   `ConfigError` for any model absent from `RATE_TABLE` — discovered on the
   first `generate()` of a long run rather than at config load. The table
   ships three hard-coded models and cannot be extended without editing
   source, contradicting "model choice everywhere" (concept §1) and the
   run-time price-verification note.

## Goal
The pipeline refuses to *start* a call that could breach the cap, and refuses
to *start a run* whose configured models have no known rates.

## Creates / changes
- `budget.py`:
  - `check_headroom(model, *, est_input_tokens, max_output_tokens)` — raises
    `BudgetExceeded` before a call whose worst-case cost (estimated input +
    the call's `max_tokens` ceiling at the model's output rate) would breach
    the cap. Estimation may be conservative (chars/4 heuristic is acceptable
    and documented).
  - rates become injectable: `BudgetGuard`/`estimate_cost_usd` accept a rate
    table; `RATE_TABLE` stays as the default.
- `config.py` — optional `budget.model_rates` section (per-model
  input/output USD per MTok) merged over the defaults; validation at load
  time that every configured stage model has a rate (fail fast with
  `ConfigError` naming the model); validate `warn_at_usd <=
  max_usd_per_run`.
- `orchestrator.py` — `_BudgetTrackedTextAdapter.generate()` calls
  `check_headroom` before `inner.generate()` and `record_usage` after.

## Acceptance criteria
- A call whose worst-case cost breaches the cap raises `BudgetExceeded`
  **before** the adapter's `generate()` is invoked (proven with a fake that
  fails the test if called).
- A config routing a stage to a rate-less model fails at `load_config` time.
- `warn_at_usd > max_usd_per_run` is rejected at load time.
- Custom `model_rates` from config drive both headroom and recording.
- Post-call recording still uses the provider's actual token counts.

## Out of scope
- Stage 3 agent-cost budgeting (T-510).
- Live pricing fetch (still a documented run-time verification step).

## Connections
- **Depends on:** T-030, T-060, T-220.
- **Blocks:** T-510.
- **Relates to:** T-310.

## Testing
**Test-first.** Cases: headroom breach blocks the call; load-time rate + warn
threshold validation; custom rates honoured; accumulation semantics unchanged.
