# T-330 — Upstream changes must invalidate downstream outputs (re-freeze + working `--from`)

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/orchestrator.py`, `src/harness/cli.py`,
`src/harness/freeze.py` (consumer wiring only)

## Problem
Concept §8/§16 and T-220's acceptance criteria require: "re-running an earlier
stage produces a new frozen version and **invalidates downstream outputs**".
None of this is implemented:

- `freeze.is_stale()` is dead code — nothing in production calls it.
- The orchestrator freezes only when **no** frozen version exists
  (`if version is None`). If the user edits `spec/concept.md` after a freeze,
  the edit is silently ignored forever: concept stage skipped (file exists),
  freeze skipped (version exists), tickets skipped (overview exists).
- The CLI's `--from <stage>` flag is validated and then **ignored** — concept
  §17 defines it as "resume from a stage", i.e. force re-execution from that
  point.

## Goal
Editing an upstream artifact, or passing `--from`, triggers a re-freeze and a
clean rebuild of everything downstream — no silent drift between the approved
spec and what gets built.

## Creates / changes
- `orchestrator.py`:
  - before skipping the freeze, compare the live `concept.md`/`guidelines.md`
    hashes against the latest frozen manifest; on mismatch, create a **new**
    frozen version and invalidate downstream outputs (move
    `spec/tickets/`, `tickets.zip`, and Stage-3 progress entries aside into a
    timestamped `spec/.invalidated/<version>/` folder — never delete user
    data silently).
  - record the invalidation as a `DECISIONS`-style journal entry.
- `cli.py` — `--from <stage>` marks that stage and everything after it as
  invalid (same mechanism), then runs.
- Stage 3 resume filtering: progress entries tied to an older frozen version
  are not treated as completed (extend `ProgressEntry` with the frozen
  version it was built against).

## Acceptance criteria
- Edit `concept.md` after a full run → next run re-freezes (new version),
  regenerates tickets, and re-implements; the old outputs are preserved under
  `spec/.invalidated/`.
- `harness run --from tickets` regenerates tickets + implementation but not
  concept/guidelines/freeze.
- Unchanged spec → no re-freeze, full idempotent skip (regression-guarded).
- `is_stale()` is exercised by production code paths.

## Out of scope
- Gate-approval persistence (T-320 — this ticket builds on it).
- Multi-phase activation (T-540).

## Connections
- **Depends on:** T-070, T-220, T-320.
- **Blocks:** T-540.
- **Relates to:** T-230 (`--from`), T-050 (journal entries).

## Testing
**Test-first.** Cases: edit-after-freeze → re-freeze + downstream rebuild;
`--from` each stage; unchanged → skip; stale progress entries not counted as
complete; invalidated outputs preserved not deleted.
