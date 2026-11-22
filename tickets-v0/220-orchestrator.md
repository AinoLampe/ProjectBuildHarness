# T-220 — Orchestrator (state machine)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/orchestrator.py`

## Goal
Implement the thin state machine that sequences the stages and applies — *around*
each stage — model/agent resolution, prompt rendering, gates, recording, and
budget tracking. The orchestrator does not "think"; it sequences and enforces
(concept §2, §5).

## Creates / changes
- `orchestrator.py`:
  - state machine `concept → guidelines → freeze → tickets → implement`.
  - per-stage routing from config (T-030); prompt rendering (T-090); gate
    application per policy (T-150); recording to the journal (T-050); budget
    tracking + halt (T-060).
  - **Idempotency:** before running a stage, check the journal/hashes; if outputs
    exist and are unchanged, skip.
  - **Resumability:** on restart, read `progress.json` and resume at the first
    incomplete unit.
  - **Freeze:** snapshot the spec (T-070) after the guidelines gate; stages 2–3
    read the frozen spec.
  - **Upstream change:** re-running an earlier stage re-freezes and invalidates
    downstream outputs (clean rebuild from that point).

## Acceptance criteria
- The full sequence runs end-to-end with fakes.
- Unchanged stages are skipped (idempotency proven by a second run doing no work).
- A simulated crash resumes correctly from `progress.json`.
- A budget breach halts the pipeline before the cap is exceeded.
- Gates are applied per policy (`interactive` / `auto_approve` / `stop`).
- Freeze happens at the §8 point; re-running an earlier stage re-freezes and
  invalidates downstream.
- Each model/agent call is recorded to `run.log` with template + version + usage.

## Out of scope
- The CLI surface (T-230).
- Parallelism / web UI (v2).

## Connections
- **Depends on:** T-030, T-040, T-050, T-060, T-070, T-090, T-150, T-160, T-170,
  T-180, T-190, T-210.
- **Blocks:** T-230, T-240.
- **Relates to:** all stages.

## Testing
**Test-first** with fakes. Cases: full sequence; idempotent skip-on-unchanged;
crash-and-resume; budget halt; gate policies; freeze point + downstream
invalidation.
