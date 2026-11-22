# T-170 — Stage 1a: Architectural concept

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/concept.py`

## Goal
Implement Stage 1a: bounded, structured brainstorming, then write the
architectural concept, self-review it, and declare phasing — emitting the
architectural source of truth (concept §6).

## Creates / changes
- `stages/concept.py` implementing the `Stage` contract.
  - **Inputs:** `requirements.md`, optional `instructions.md`.
  - **Outputs:** `spec/concept.md`, `spec/open-questions.md`,
    `spec/phasing.yaml`.
  - Produce a categorised, severity-tagged `open-questions.md` (Assumptions /
    Decisions needed / Suggested improvements).
  - **Bounded interactive loop:** user answers inline; loop capped by
    `brainstorm.max_rounds`; on exhaustion of blocking items, record explicit
    assumptions and proceed (`proceed_with_documented_assumptions`) — guaranteed
    termination.
  - Write `concept.md`, then a **self-review pass**; any new blocking question
    re-enters the loop (still under the cap).
  - Declare phasing in `concept.md` + `spec/phasing.yaml` (active phase +
    `stop_after_active_phase`), or state explicitly that none is needed.
  - Enforce the **readiness checklist** (concept §6.4) before "ready".

## Acceptance criteria
- Emits the three declared outputs and touches no others (declared-IO).
- The brainstorm loop **always terminates** — within the round cap, or via
  documented assumptions on exhaustion.
- A concept is "ready" only when the readiness checklist is satisfied.
- When phasing is declared, `phasing.yaml` marks exactly one active phase and
  sets `stop_after_active_phase`.
- Driven end-to-end with `FakeTextAdapter` scripting the Q&A and the writes.

## Out of scope
- The approve gate itself (orchestrator applies it via T-150).
- Guidelines generation (T-180).

## Connections
- **Depends on:** T-160, T-090, T-100, T-040.
- **Blocks:** T-220.
- **Relates to:** T-150 (gate), T-080 (phasing later scopes the DAG).

## Testing
**Test-first** for the loop/readiness/termination logic; **fake-adapter** for the
generation. Cases: round-cap exhaustion → documented assumptions; self-review
re-entry; readiness checklist enforcement; phasing declared vs none.
