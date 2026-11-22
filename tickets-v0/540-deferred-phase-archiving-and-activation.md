# T-540 — Deferred-phase ticket archiving + phase activation

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/stages/tickets.py`, `src/harness/cli.py`,
`src/harness/orchestrator.py`, `src/harness/folder.py`

## Motivation
Stage 2 currently **discards** tickets the model wrote for non-active phases —
`filter_active_phase` drops them and nothing archives them (concept §20 lists
cross-phase archiving as an open item). Combined with the phase-boundary stop
(T-300), a phased project dead-ends: after phase 1 there is no way to
activate phase 2 short of hand-editing `phasing.yaml` and hand-deleting state
so stages re-run. The concept's model — "later phases are deferred until their
phase becomes active" (§9.4) — needs the deferral to be a *place*, and
activation to be a *command*.

## Creates / changes
- `folder.py` — `spec/tickets/deferred/<phase-id>/` path accessor.
- `tickets.py` — write non-active-phase tickets to the deferred folder
  (excluded from `tickets.zip` and from Stage 3's glob, which already only
  reads `spec/tickets/*.md`); record the deferral count in the stage result.
- `cli.py` — `harness phase --project <dir> [--next | --activate <id>]`:
  - validates the current phase completed (all its tickets in
    `progress.json`, no open escalations);
  - updates `phasing.yaml` (`active` flags) with the injected Clock/journal
    trail;
  - promotes the newly-active phase's deferred tickets into
    `spec/tickets/`, regenerating the overview's build order for the
    combined state (dependencies on completed phase-1 tickets resolve as
    already-satisfied — needs T-360's cross-phase edge handling);
  - the next `harness run` then implements the newly-active phase through
    the normal Stage 3 path.
- `orchestrator.py` — phase-boundary halt message points at `harness phase
  --next`.

## Acceptance criteria
- A fake run with two declared phases leaves phase-2 tickets under
  `spec/tickets/deferred/phase-2/`, not lost, not implemented.
- `harness phase --next` after a completed phase 1: phasing.yaml flips,
  deferred tickets promoted, and a subsequent run implements exactly them
  (fake-proven), skipping completed phase-1 work.
- `--next` before phase 1 completes → refused with the incomplete ticket ids.
- Dependencies from phase-2 tickets onto completed phase-1 tickets order
  correctly (treated as satisfied).

## Out of scope
- Re-planning phase 2 against as-built reality (a possible future
  "phase-start replan" stage — genuinely v2).
- Multi-phase parallelism.

## Connections
- **Depends on:** T-190, T-300, T-330, T-360.
- **Blocks:** none.
- **Relates to:** T-230, T-050.

## Testing
**Test-first.** Cases: deferral placement + zip exclusion; activation flip +
promotion + build-order regeneration; premature activation refused;
cross-phase dependency satisfaction.
