# T-070 — Spec freeze + content hashing

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/freeze.py`

## Goal
Snapshot the agreed spec (`concept.md` + `guidelines.md`) into an immutable,
versioned, content-hashed lock before any code is written, so stages 2 and 3
build against exactly what the user approved and silent drift is impossible
(concept §8, principle §1.5).

## Creates / changes
- `freeze.py`:
  - snapshot `spec/concept.md` and `spec/guidelines.md` into
    `spec/.lock/<timestamp>/`, recording content hashes (for `run.log`).
  - frozen-read-by-hash accessor for downstream stages.
  - invalidation: re-running an earlier stage produces a **new** frozen version
    and marks downstream outputs invalid (concept §8, §16).

## Acceptance criteria
- A snapshot creates a timestamped lock dir containing copies + recorded hashes.
- A frozen snapshot is immutable — nothing rewrites it once created
  (guidelines §3 "the frozen spec is immutable").
- Re-freezing after an upstream change yields a new version and invalidates
  downstream outputs.
- Timestamps from the injected `Clock`; hashes are stable/content-addressed.

## Out of scope
- Deciding *when* to freeze (orchestrator triggers it after the guidelines gate,
  T-220).
- Stage logic that consumes the frozen spec (T-190, T-210).

## Connections
- **Depends on:** T-020, T-040.
- **Blocks:** T-190 (tickets read frozen spec), T-220.
- **Relates to:** T-050 (hashes recorded in run.log).

## Testing
**Test-first.** Cases: snapshot + hash; immutability; re-freeze → new
version + downstream invalidation.
