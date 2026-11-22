# T-200 — Per-ticket review gate (tests + LLM review)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/review.py` (helper used by `implement.py`)

## Goal
Implement the per-ticket review gate: a ticket is complete only when the
automated checks are green **and** an independent LLM reviewer — running in a
fresh, isolated session — confirms it. The gate is driven by the **orchestrator**,
not by the implementer, to eliminate the "agent grading its own work" problem
(concept §10.3, principle §1.7).

## Creates / changes
`review.py` — a `run_review_gate(ticket, folder, adapter, config) -> GateResult`
function that:

1. **Automated checks (objective, hard signals).** Inside the sandbox (T-120):
   - Run `pytest` scoped to the ticket's test files → pass/fail + output.
   - Run `ruff check` + `ruff format --check` → pass/fail.
   - Run the strict type checker → pass/fail.
   These run first. If any are red, the gate **fails immediately** without
   calling the reviewer — the LLM verdict cannot override a failing test suite.

2. **LLM review (semantic, via the orchestrator's adapter call).** Only reached
   when automated checks are green. The orchestrator:
   - Builds the review prompt from the T-090 template, injecting: the ticket
     text (Goal, Acceptance criteria, Out of scope), the paths of changed files,
     and the objective-check results.
   - Calls **`adapter.review()`** (T-140) — a fresh `claude -p` process, read-only
     tools, `config.models.review` model. The reviewer has never seen the
     implementer's session; it receives only what the orchestrator explicitly
     passes.
   - Parses the structured verdict: `{"pass": bool, "reasons": [str]}`.
   - An unparseable response is treated as reviewer failure.

3. Returns `GateResult(passed: bool, objective: ObjectiveResult,
   llm_verdict: ReviewResult | None, reasons: list[str])` — structured for the
   journal.

**Parallelism seam (v0: sequential; v2: parallel).** Because each reviewer is an
independent process with no shared state, this function is written as `async` and
uses `await adapter.review(...)`. In v0 the orchestrator awaits them one at a
time; in v2 it fans them out with `asyncio.gather()` across independent DAG
tickets — no refactoring required.

## Acceptance criteria
- Automated checks red → gate fails; `adapter.review()` is never called.
- Automated checks green + reviewer rejects → gate fails.
- Both pass → `GateResult.passed = True`; ticket eligible for "complete".
- The reviewer invocation is a fresh session (no shared context with the
  implementer). Validated by asserting `adapter.review()` is called — not
  `adapter.run()` — and that the prompt is assembled by the gate, not delegated
  to the implementer.
- Returns a structured `GateResult` suitable for the journal (T-050).
- The function signature is `async`; awaiting it in a loop (v0) and gathering
  it in parallel (v2) are both valid callers.

## Out of scope
- The retry loop and escalation on gate failure (T-210).
- The final acceptance pass against `requirements.md` (T-210).
- Parallelising the reviewer calls (v2 — the seam is built here, the gather
  goes in T-210/T-220).

## Connections
- **Depends on:** T-120 (sandbox for automated checks), T-130 (adapter
  protocol), T-140 (fresh-session reviewer), T-090 (review prompt template),
  T-040 (folder paths).
- **Blocks:** T-210.
- **Relates to:** T-050 (GateResult journaled), T-220 (orchestrator drives the
  await / future gather).

## Testing
**Test-first** for the gate logic; **fakes** for the adapter and sandbox.

Key cases:
- Automated checks fail → reviewer never called, gate fails.
- Automated checks pass + reviewer passes → `GateResult.passed = True`.
- Automated checks pass + reviewer rejects → `GateResult.passed = False`.
- Unparseable reviewer response → treated as reviewer failure.
- `adapter.review()` receives an orchestrator-assembled prompt, not one composed
  by the implementer.
- `async` function: awaitable in a loop and gatherable concurrently (smoke test
  with two fake reviews in `asyncio.gather`).
