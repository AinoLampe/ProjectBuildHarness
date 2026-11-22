# T-670 — Epic gate: pending end-to-end acceptance tests written first (TDD), activated and enforced when the epic completes

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `src/harness/stages/implement.py`, `src/harness/stages/review.py`,
`src/harness/journal.py`, `src/harness/folder.py`, `src/harness/config.py`,
`src/harness/cli.py`, `src/harness/prompt_templates/v1/`
(`epic_acceptance_test_write.md`, `epic_review.md`, `epic_close.md` new;
`implement_bootstrap.md`, `implement_round.md`, `final_acceptance.md` gain variables)

## Motivation
R6: after an epic is completely finished there is an end-to-end test, which may be
written beforehand because TDD is the standard. Today verification is per ticket
(scoped tests, T-520), one full-suite pass at the end of Stage 3, and an LLM-only final
acceptance pass; nothing checks that an epic's tickets *together* deliver the
capability. A test written first is red until the epic's last ticket lands — and every
ticket gate runs `pytest` (the full suite for tickets without a declared scope, plus
the stage-end regression net), so a red acceptance test inside the target's `tests/`
tree would fail every gate; under pyright strict an e2e test importing not-yet-existing
modules would not even type-check. The test must exist before the code — visible to
every ticket's IA — without being part of any ticket gate (concept v1.1 §10.7).

## Goal
Each epic starts with a harness-owned acceptance-test unit that writes the e2e tests
for the epic's scenarios into a **pending** location and records the expected red;
each epic ends with an epic gate that activates the tests, runs them with the full
suite and the linters, has the RA review the epic as a whole, and on failure runs the
T-660 dialogue on an `E0N::close` unit; exhaustion escalates with proposals.

## Creates / changes
- `folder.py` — `spec_epic_acceptance_dir(epic_id)` =
  `spec/tickets/epics/<epic_id>/acceptance/` (pending tests: outside the target's test
  tree, so no check ever collects them); `tests_e2e_dir(epic_id)` =
  `tests/e2e/<epic_id>/` (activated); `journal_epics_dir`; `journal_unit_dir` maps
  `E0N::*` units to `journal/epics/<E0N>/`.
- Unit ids in `resume_state`: `[E01::acceptance-test, <E01 tickets…>, E01::close,
  E02::acceptance-test, …, __final_acceptance__]` (T-640's grouped order expanded by
  `expand_units`); `ProgressEntry.ticket` holds the unit id (no schema change).
- `stages/implement.py` —
  - `_write_acceptance_tests(epic)`: an IA turn with `epic_acceptance_test_write.md`
    (`{{epic_text}}` incl. scenarios, the source-of-truth paths, project state,
    `{{pending_dir}}`; rules: tests exercise the capability through its public
    interface only, may not stub the epic's own code, are expected to fail now, and
    the turn ends with a `ResolutionReport`). The IA writes files under the pending
    dir. Gate for this unit: `ruff check <pending dir>` green (syntax/style — **not**
    pyright, **not** a green run); the tests are executed once in the sandbox
    (`pytest <pending dir>`) and the result recorded as
    `journal/epics/<id>/acceptance-baseline.json` (`expected_red: bool`, output
    tail) — a *green* baseline is itself a `major` finding ("the acceptance test does
    not test the epic"); then an RA review with `epic_review.md` in `{{mode}}` =
    `acceptance-test` (scenario coverage, no stubbing) through `_run_dialogue`
    (T-660). Disabled by `implementation.epics.acceptance_tests: false` (unit
    skipped; one `DecisionRecord` per run).
  - Ticket prompts (`implement_bootstrap.md`, `implement_round.md`) gain
    `{{epic_file_path}}` and `{{pending_acceptance_dir}}` ("the epic's acceptance
    tests live here; do not modify them; your ticket should move them toward green").
  - `_run_epic_gate(epic)` after the epic's last ticket passes: move the pending tests
    to `tests/e2e/<id>/` (no-op when disabled); `run_epic_gate_checks` =
    `run_objective_checks(sandbox, [tests_e2e_dir])` then `run_objective_checks(
    sandbox, [])` — both green — then the RA `epic_review.md` in mode `close` (epic
    goal and scenarios, its tickets with their final resolution summaries, changed
    files across the epic from the union of round reports, objective output) →
    `ReviewFindings`. Green + `pass` → `record_progress(E0N::close)`. Otherwise
    `_run_dialogue` on unit `E0N::close` with `epic_close.md` as the IA prompt
    (failing output + ledger; the IA may fix code **or** tests; the RA template states
    that a weakened or deleted acceptance test is a `blocker`), bounded by
    `max_review_rounds`; exhaustion → escalation kind `epic_gate` for unit
    `E0N::close` with proposals.
  - Final acceptance pass: an objective component first — all activated epic tests +
    the full suite green, run once as the increment's regression net (replacing
    T-520's single full-suite pass) — then the LLM drift check; `final_acceptance.md`
    gains `{{epics}}` (ids, goals, scenario counts).
- `stages/review.py` — `run_epic_gate_checks(sandbox, e2e_dir) -> ObjectiveResult`
  (thin wrapper sequencing the two `run_objective_checks` calls; T-700 later routes it
  through the declared `e2e_test` command); `{{mode}}` handling for `epic_review`.
- `journal.py` — `record_round` accepts epic unit ids (paths via `journal_unit_dir`);
  `acceptance-baseline.json` writer/reader.
- `config.py` — `EpicsConfig(acceptance_tests: bool = True)` as
  `ImplementationConfig.epics`.
- `cli.py` — `status`: per epic — acceptance-test unit state (pending / written /
  activated), tickets done/pending, gate state; the escalation summary prints
  epic-gate proposals like ticket ones; `resolve --ticket E01::close` accepted.
- Templates: three new, three extended; consistency test extended.

## Acceptance criteria
- Two-epic fake run: unit order `E01::acceptance-test, T-010, T-020, E01::close,
  E02::acceptance-test, T-030, E02::close, __final_acceptance__`; the acceptance-test
  IA prompt names the pending dir and the scenarios; the fake IA writes a test file
  there; the baseline records red; ticket gates never run `pytest` on the pending dir
  (`RecordingSandbox` asserts every command); at `E01::close` the file is moved to
  `tests/e2e/E01/`, then `pytest tests/e2e/E01` and `pytest` run, then the RA `close`
  review.
- Green baseline at the acceptance-test unit → a `major` finding in that unit's RA
  prompt.
- Epic gate failure (scripted red e2e run) → `epic_close` IA round(s) through the T-660
  loop; with `max_review_rounds: 1` → escalation kind `epic_gate` for unit
  `E01::close` with proposals; clean halt; `harness resolve --ticket E01::close
  --choose 1` then a re-run resumes at the gate, not at the epic's tickets.
- `acceptance_tests: false`: no acceptance-test units; the gate runs the full suite
  plus the RA close review only; one decision recorded per run.
- Crash-and-resume: progress entries for `E01::acceptance-test` and the epic's tickets
  are skipped on resume; an unrecorded gate unit is re-run.
- The final pass runs the objective regression net once (fake sandbox counts exactly
  one full `pytest` after all epics) before the reviewer call.

## Out of scope
- Non-Python e2e runners (T-700 makes the command declarable; this ticket runs
  `pytest` paths through `run_objective_checks`).
- Parallel epics (v2).
- UI/browser-driven e2e infrastructure in the container (network stays as configured).

## Connections
- **Depends on:** T-600, T-640, T-660, T-200, T-410, T-520.
- **Blocks:** T-700.
- **Relates to:** T-530, T-560, T-650.

## Testing
**Test-first** for unit expansion/ordering, baseline rules, the activation move, gate
sequencing, escalation kind/unit id, resume behaviour, the config off-switch; fakes
throughout (`FakeCodingAgent` writes the pending test file; `RecordingSandbox` asserts
the exact `pytest` invocations and their order).
