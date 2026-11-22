# T-050 — Journal (run.log + DECISIONS / PROGRESS + JSON mirrors)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/journal.py`

## Goal
Record everything the run does and provide the machine-readable basis for
resumability (concept §10.5, §14): a structured `run.log`, plus human + machine
mirrors of decisions and per-ticket progress.

## Creates / changes
- `journal.py`:
  - `run.log` append: one JSON object per line carrying stage, provider/agent,
    model, prompt template + version, input/output token counts, estimated cost,
    wall time, and the content hash of each artifact written.
  - `DECISIONS.md` + `decisions.json` — every conflict/ambiguity + reasoning.
  - `PROGRESS.md` + `progress.json` — one entry per ticket (ID, summary,
    deviations and why).
  - Read helper that reconstructs resume state from `progress.json`
    (completed / incomplete units).

## Acceptance criteria
- `run.log` is valid JSON-lines (one object per line, parseable independently).
- Decisions and progress write the markdown and JSON mirrors and keep them in
  sync (write once, both updated).
- `progress.json` round-trips and yields a resume state listing completed vs
  incomplete units.
- Timestamps come from an injected `Clock` (deterministic in tests).
- A missing or empty journal is handled gracefully (fresh run).

## Out of scope
- Deciding *what* to resume or skip (orchestrator, T-220).
- Budget thresholds (T-060) — journal only records the numbers it is given.

## Connections
- **Depends on:** T-020, T-040.
- **Blocks:** T-180, T-200, T-210, T-220, T-230.
- **Relates to:** T-060 (orchestrator wires budget halts into the log).

## Testing
**Test-first.** Cases: run.log line is independently parseable; md/json mirror
sync; progress round-trip → resume state; corrupt/missing journal handled.
