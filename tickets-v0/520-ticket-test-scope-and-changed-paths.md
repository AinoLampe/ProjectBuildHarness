# T-520 — Ticket-declared test scope + real changed-path detection for the reviewer

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/stages/tickets.py` (schema/prompt),
`src/harness/stages/implement.py`, `src/harness/stages/review.py`,
`src/harness/prompt_templates/v1/tickets.md`

## Motivation
Two compromises currently blunt the review gate:

1. DECISIONS.md (T-210): because the ticket schema has no test-scope field,
   every gate run executes the **whole** test suite of the target project.
   Correctness-preserving, but on an N-ticket project the suite runs N times
   at increasing size — the pipeline slows quadratically, and a flaky test in
   ticket 3's area blocks ticket 17. The decision itself points at the fix:
   a schema field, specified rather than guessed.
2. `ImplementStage` passes `changed_paths=[src/]` — the reviewer is told
   "everything changed" every time. A reviewer that cannot see *what changed*
   reviews the whole codebase per ticket: slower, costlier, and less likely
   to spot out-of-scope edits (the very thing it must check).

## Creates / changes
- Ticket schema (Stage 2 prompt + T-500 contract): a required
  `### Tests` section listing the test files/dirs that cover the ticket
  (created or extended by it). The overview's conventions section documents
  it.
- `implement.py`:
  - parse the ticket's test scope; run the gate **scoped first, then the full
    suite once at the end of the stage** (fast per-ticket signal, final
    global regression net — replaces N full-suite runs with N scoped + 1
    full).
  - changed-path detection: snapshot the project tree (mtime/hash walk of
    `src/` + tests) before `adapter.run()`, diff after; pass the real changed
    set to the gate. Flag writes **outside** the ticket's declared
    creates/changes as a review input ("undeclared changes: …").
- `review.py` — accept and forward the scoped test paths + changed set;
  include undeclared-change flags in the review prompt variables.

## Acceptance criteria
- Per-ticket gate runs only the ticket's declared tests (fake sandbox records
  commands); the stage's final acceptance still runs the full suite once.
- A ticket with no `### Tests` section fails Stage 2 validation (schema),
  not Stage 3 guessing.
- The reviewer prompt lists exactly the files the fake agent wrote, and calls
  out one it wrote outside the declared scope.
- Wall-clock: a 5-ticket fake pipeline executes 5 scoped + 1 full pytest
  invocation (not 5 full).

## Out of scope
- Git-based diffing (folder may not be a repo; tree-walk is sufficient for
  v0.2 — revisit when the workspace is git-guaranteed).
- Parallel gates (v2).

## Connections
- **Depends on:** T-190, T-200, T-210; schema field lands with T-500's
  contract.
- **Blocks:** none.
- **Relates to:** T-410 (final full-suite pass pairs with final acceptance).

## Testing
**Test-first.** Cases: scoped command construction; missing-Tests-section
rejection; changed-set accuracy incl. undeclared write; invocation-count
budget.
