# T-620 — Increment model: one run = one immediate requirements document over the current project; phasing dormant by default

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `src/harness/orchestrator.py`, `src/harness/journal.py`,
`src/harness/folder.py`, `src/harness/config.py`, `src/harness/stages/concept.py`,
`src/harness/cli.py`, `src/harness/core/ids.py` (reuse),
`src/harness/prompt_templates/v1/concept_write.md`

## Motivation
R2: everything in `requirements.md` is to be built now; later versions are later
requirements. Two things in the harness contradict this. (1) Concept §6.3 (v1.0) lets
the concept author carve the requirements into phases ("a smaller first version is the
sensible deliverable"), and T-300/T-540 stop at the phase boundary and archive deferred
tickets — the harness may decide *not* to build part of what the user asked for.
(2) There is no notion of "the next requirements": `Orchestrator._ensure_stage_gated`
keys idempotency on artifact presence plus the gate's artifact hash, never on the
content of `requirements.md`, so replacing `requirements.md` on a finished project and
running again does **nothing** — every stage is approved and every ticket is done.
R1 and R2 together define the intended model (concept v1.1 §1, §6.3): an *increment*
is one immediate requirements document applied to the current project folder, empty
or not; "later versions" are new increments. This also closes concept §20's
cross-phase archiving item: in the default mode no deferred tickets exist.

## Goal
A run belongs to an increment identified by the requirements' content hash; a changed
`requirements.md` starts a new increment (prior spec archived, survey re-run, concept
regenerated with the project state as input); phasing is off by default and remains
available behind a config switch.

## Creates / changes
- `journal.py` — `IncrementRecord(id: str, requirements_sha256: str, started_at:
  datetime, status: Literal["active","archived"])`; id `inc-NNNN` with NNNN = 1 +
  the number of archived increments under `spec/.history/` (zero-padded, via
  `core/ids.py`). Stored at `spec/increment.json` (the single current record; the
  archived copy travels into `spec/.history/<id>/increment.json`).
  `active_increment(folder) -> str | None` reads it. `RunLogEntry`, `ProgressEntry`,
  `DecisionRecord`, `GateOutcome`, `EscalationRecord` gain `increment: str | None =
  None` (backward compatible, like `frozen_version` in T-330); every `record_*`
  function stamps `active_increment(folder)` unless the caller supplied one.
  `resume_state` is unchanged — a new increment archives `progress.json`, so no
  filtering is needed.
- `folder.py` — `spec_increment_json`, `spec_history_dir`,
  `spec_history_increment_dir(id)`.
- `orchestrator.py` — `_ensure_increment() -> IncrementRecord`, called first in
  `run()`: no record → create `inc-0001`; equal hash → continue (idempotent);
  different hash → `_start_new_increment(old, new_hash)`: **refuse** with a clean
  halt (`halt_reason="escalation"`, message naming the open escalations, exit code 5
  via the existing CLI path) if any escalation is open; otherwise move aside into
  `spec/.history/<old-id>/` via `_move_aside` (never delete): `spec/concept.md`,
  `guidelines.md`, `open-questions.md`, `phasing.yaml`, `project-state.md`/`.json`,
  `requirements-normalised.md`/`.json` (T-680), `checks.yaml` (if present),
  `tickets/` (including `epics/` and `deferred/`),
  `tickets.zip`, `.lock/`, `journal/PROGRESS.md`, `progress.json`,
  `journal/tickets/`, `journal/epics/`; keep `run.log`, `DECISIONS`, `GATES`,
  `ESCALATIONS` (append-only, now tagged by increment); record a `DecisionRecord`
  ("requirements changed: increment <new> started, <old> archived"); write the new
  record. `src/`, `tests/` and everything else the previous increment built are
  **not touched** — they are the project state the next survey reads.
- `config.py` — `ImplementationConfig.phasing: Literal["single","concept_decides"] =
  "single"`.
- `stages/concept.py` — new field `phasing_policy`; `concept_write.md` gains
  `{{phasing_instruction}}`: in `single` mode "Everything in the requirements is in
  scope for this increment. Declare **no** phasing: the `## Phasing` section states
  that none is needed. Do not defer any requirement to a later phase or version."; in
  `concept_decides` mode the v0 wording. After `extract_phasing_yaml`, a concept that
  declares phases under `single` gets **one** bounded re-ask through the existing
  `concept_revise` template with a folding instruction; if it still declares phases →
  `StageError` naming the policy. Readiness's "phasing decision" item stays satisfied
  by the explicit "none needed" statement.
- `cli.py` — `harness phase` prints "phasing is disabled (implementation.phasing:
  single)" and exits 1 in `single` mode; `status` prints the active increment id, the
  requirements hash prefix and the archived increments; `run` prints "starting
  increment <id>" when one starts.

## Acceptance criteria
- Fresh project: `run()` creates `spec/increment.json` (`inc-0001`, sha256 of
  `requirements.md`); a second run with unchanged requirements makes zero adapter
  calls (existing idempotency, now also asserted against the increment record).
- Changed requirements after a completed run: the next `run()` archives every listed
  artifact into `spec/.history/inc-0001/` (asserted path by path; nothing deleted),
  creates `inc-0002`, re-runs the survey in `existing` mode (increment 1's `src/` is
  present and untouched) and the concept; progress starts empty; the decision is
  journaled with `increment: inc-0002`.
- Changed requirements while an escalation is open: clean halt naming the escalation;
  nothing archived; exit code 5.
- `phasing: single` (default): a concept declaring phases triggers exactly one re-ask;
  a still-phased concept → `StageError`; a compliant concept yields `phases: []` and
  the run never halts at a phase boundary. `phasing: concept_decides`: T-300/T-540
  behaviour unchanged (existing phase tests pass with the policy set explicitly).
- All journal records written during a run carry the active increment id;
  pre-existing journals without the field still load.

## Out of scope
- Re-planning across increments (diffing the old and new concept) — the survey plus a
  fresh concept is the mechanism.
- Deleting history (never).
- Survey internals (T-610).

## Connections
- **Depends on:** T-600, T-610, T-020, T-050, T-300, T-320, T-330, T-530, T-540.
- **Blocks:** T-680.
- **Relates to:** T-560, T-640, T-720.

## Testing
**Test-first.** Cases: first-run record creation; unchanged-hash idempotency;
changed-hash archive list (every path moved, `src/` untouched, nothing deleted);
refusal while an escalation is open; `single` re-ask-then-error and compliant paths;
`concept_decides` regression (existing phase tests parametrised over the policy);
increment tags on records; old journals load.
