# T-390 — Journal writes must truly append; freeze versions must not collide

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/journal.py`, `src/harness/folder.py`,
`src/harness/freeze.py`

## Problem
1. **`append_run_log` rewrites the whole file per append.** It reads the full
   existing log and writes `existing + line` back. Cost grows quadratically
   over a long run, and a crash mid-write can corrupt or truncate the
   *entire* history — the exact artifact resumability depends on. The
   markdown/JSON mirrors (`record_decision`, `record_progress`) share the
   read-modify-write pattern; for `progress.json` (the crash-recovery basis,
   concept §10.5) a truncating crash silently voids resume state.
2. **Freeze versions collide at second granularity.** `freeze_spec` derives
   the version from `%Y%m%dT%H%M%SZ`; two freezes within the same second (or
   a test with an unadvanced `FrozenClock`) raise `FolderError` even though
   nothing is wrong. With T-330's re-freeze flow this becomes reachable in
   normal operation.

## Goal
Journal appends are O(1) and crash-tolerant; freezing twice in quick
succession yields two distinct versions.

## Creates / changes
- `folder.py` — an `append_text(path, content)` helper (opens in append mode,
  creates parents), used by `append_run_log` and the markdown mirror appends.
- `journal.py`:
  - `append_run_log` uses append mode — no read of prior content.
  - JSON mirrors written atomically: write to a temp file in the same
    directory, then `os.replace` (crash leaves either old or new state,
    never a truncated file).
- `freeze.py` — on version collision, disambiguate deterministically (append
  `-2`, `-3`, … suffix) instead of raising; `latest_version` ordering still
  correct for suffixed versions.

## Acceptance criteria
- Appending N run-log entries reads the existing file zero times (proven via
  a counting fake or file-op spy) and yields N parseable JSON lines.
- A simulated crash between temp-write and replace leaves the previous valid
  JSON mirror intact (test by injecting a failing replace).
- Two `freeze_spec` calls with an unadvanced clock produce two versions;
  `latest_version` returns the second; `read_frozen` works for both.
- All existing journal/freeze round-trip tests stay green.

## Out of scope
- Journal content/schema changes (T-310, T-320 own those).
- Log rotation/compaction.

## Connections
- **Depends on:** T-040, T-050, T-070.
- **Blocks:** none (hardening).
- **Relates to:** T-330 (re-freeze makes collisions reachable), T-310.

## Testing
**Test-first.** Cases: append without read; atomic-replace crash simulation;
same-second double freeze; suffixed-version ordering.
