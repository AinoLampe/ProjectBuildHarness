# T-180 — Stage 1b: Engineering guidelines

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/guidelines.py`

## Goal
Implement Stage 1b: generate the engineering guidelines from the concept in a
**fresh context**, then consolidate the two artifacts with the concept winning
any conflict (concept §7).

## Creates / changes
- `stages/guidelines.py` implementing the `Stage` contract.
  - **Inputs:** `spec/concept.md` **only** (no brainstorming history — this is
    how "fresh session" is enforced structurally).
  - **Outputs:** `spec/guidelines.md`, and a revised `spec/concept.md` *only if*
    consolidation changed it.
  - Generate guidelines: general best practices + stack/project-specific rules +
    explicitly AI-coding-friendly rules; mandate meaningful automated tests with
    a test-first discipline where it fits (and the review gate requires them
    green); plus conventions for lint/format, error handling, logging, naming,
    commit/PR structure, and directory layout.
  - **Consolidation check** vs the concept; on conflict, harmonise with the
    **concept winning** and record the change in `DECISIONS.md`.

## Acceptance criteria
- The stage's only input is `concept.md` (a test proves no brainstorming history
  reaches it).
- Emits `guidelines.md` (+ a revised `concept.md` only when changed).
- Any concept/guidelines conflict is resolved concept-first and logged to
  `DECISIONS.md`/`decisions.json`.
- Compatible with `guidelines: auto_approve` gate policy.
- Driven with `FakeTextAdapter`.

## Out of scope
- Gate application (T-150 / orchestrator).
- Ticket writing (T-190).

## Connections
- **Depends on:** T-160, T-090, T-100, T-040, T-050 (decisions log).
- **Blocks:** T-220.
- **Relates to:** T-070 (its output is frozen next).

## Testing
**Test-first** for the consolidation/precedence logic; **fake-adapter** for
generation. Cases: input is concept-only; conflict → concept wins + logged;
no-change leaves concept untouched.
