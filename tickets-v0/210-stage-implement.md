# T-210 — Stage 3: Implementation driver

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/implement.py`

## Goal
Implement Stage 3: drive the coding agent through the tickets in dependency
order, gate each with the review gate, retry-then-escalate on failure, journal
everything, and close the loop with a final acceptance pass against the original
requirements (concept §10).

## Creates / changes
- `stages/implement.py` implementing the `Stage` contract.
  - **Inputs:** frozen `spec/concept.md`, frozen `spec/guidelines.md`, all
    `spec/tickets/*.md`.
  - **Writes:** `src/`, `journal/DECISIONS.md` (+`decisions.json`),
    `journal/PROGRESS.md` (+`progress.json`).
  - **Bootstrap (injected once):** instruct the agent to read concept →
    guidelines → overview → remaining tickets; resolve doc conflicts by a
    reasonable decision logged in `DECISIONS.md` (concept outranks guidelines);
    **escalate genuine ambiguity to the user**, never guess.
  - **Dependency-ordered execution:** implement tickets in the build order from
    the overview DAG (topological sort, T-080).
  - Run each ticket through the **review gate** (T-200).
  - **Retry budget + escalation:** retry a failing ticket up to
    `implementation.retry_budget` (default 2), then **stop and escalate to the
    user** with failure context — no thrashing, no shipping a broken ticket.
  - **Journals:** per-ticket `PROGRESS` entry (ID, summary, deviations);
    `progress.json` drives crash recovery.
  - **Final acceptance pass:** after all active-phase tickets pass, validate the
    **assembled implementation against `requirements.md`** (not just the
    tickets), to catch concept drift; then send the user a confirmation prompt.
  - Stop at the phase boundary.

## Acceptance criteria
- Tickets run in topological order (dependencies exist before dependents).
- A failing ticket retries ≤ budget then escalates (`escalate_to_user`); never
  ships a failed ticket or loops forever.
- Journals updated per ticket and drive resume from `progress.json`.
- The final acceptance pass runs against `requirements.md` and surfaces drift.
- Stops at the active-phase boundary.
- Fully exercised with `FakeCodingAgent` — no real models, containers, or spend.

## Out of scope
- Parallel execution of independent DAG branches (v2).
- Real-agent specifics (T-140) and review internals (T-200).

## Connections
- **Depends on:** T-160, T-200, T-080, T-130, T-140, T-120, T-050, T-040.
- **Blocks:** T-220.
- **Relates to:** T-090 (bootstrap template), T-110 (acceptance-pass review).

## Testing
**Test-first** for ordering / retry / escalation / resume / final-acceptance
logic; **fakes** for the agent. Cases (incl. guidelines §4.4): build-order
respected; retry-budget exhaustion → escalate; crash-and-resume; final pass
catches drift; phase stop.
