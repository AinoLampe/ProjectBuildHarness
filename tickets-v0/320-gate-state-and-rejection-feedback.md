# T-320 — Persist gate outcomes; a rejected artifact must not pass on re-run

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/orchestrator.py`, `src/harness/journal.py`,
`src/harness/gates.py` (surface only), `src/harness/cli.py`

## Problem
The orchestrator's idempotency check is "does the stage's primary output file
exist" (`orchestrator.py` `run()`). Gate approval is not persisted anywhere, so
**generated** is conflated with **approved**:

1. A user rejects the concept at the gate → `GateRejected` halts the run, but
   `spec/concept.md` already exists on disk. The next `harness run` **skips the
   concept stage entirely** and proceeds to build on the artifact the user
   explicitly rejected.
2. The rejection feedback is lost — not journaled, never fed back into a
   regeneration (concept §11: reject = "send it back **with feedback**").
3. A crash between generation and gate approval is indistinguishable from an
   approved stage on resume.

## Goal
A stage counts as complete only when its artifact was generated **and**
approved; rejection feedback is persisted and drives regeneration.

## Creates / changes
- `journal.py` — a `GateOutcome` record (stage, decision, artifact content
  hash, feedback, timestamp) written to the journal (JSON mirror + markdown),
  reusing the existing mirror-write pattern.
- `orchestrator.py`:
  - skip a text stage only when its output exists **and** the journal holds an
    `approve`/`edit` outcome whose hash matches the current file content.
  - on `GateRejected`: record the outcome + feedback, then **re-run the stage
    once** with the feedback injected into the stage prompt variables; a second
    rejection halts the run (bounded, no infinite loop).
- `cli.py` — `harness gate --reject` records the same journal outcome so a
  later `harness run` regenerates instead of skipping.

## Acceptance criteria
- Reject → re-run: the regeneration prompt contains the user's feedback; a
  fake-driven test proves the stage adapter is called again.
- Two consecutive rejections halt with a clear message (no loop).
- After a rejection halt, a fresh `harness run` regenerates the rejected
  stage; it never silently reuses the rejected artifact.
- A crash before gate approval → resume re-applies the gate (the stage output
  may be reused, but the gate runs again).
- Approved runs behave exactly as today (regression-guarded by T-240).

## Out of scope
- Upstream-change invalidation of *downstream* stages (T-330).
- Gate UX improvements (editor integration etc.).

## Connections
- **Depends on:** T-050, T-150, T-220.
- **Blocks:** T-330 (shares the journal-backed stage-state mechanism).
- **Relates to:** T-230.

## Testing
**Test-first.** Cases: reject→regenerate-with-feedback; double-reject halt;
reject-then-rerun regenerates; crash-before-gate re-gates on resume; hash
mismatch (file edited after approval) re-gates.
