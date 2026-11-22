# T-560 — Observability surface: spend, per-stage cost, and run history in `harness status`

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/cli.py`, `src/harness/journal.py` (read helpers)

## Motivation
Concept §14 makes observability a first-class principle, and T-310 makes the
data exist — but the only consumer is a human opening JSON files. `harness
status` today prints progress/decision counts and nothing about the two
things an unattended-run operator actually asks: *what is it costing me* and
*where is it stuck*. The run.log's purpose ("what makes prompt optimisation
measurable", §14) needs an aggregation surface before anyone can act on it.

## Creates / changes
- `journal.py` — pure aggregation helpers over `read_run_log`:
  `spend_by_stage()`, `spend_total()`, `calls_by_template()` (template name +
  version → calls, tokens, cost — the prompt-A/B primitive).
- `cli.py` — `status` output becomes:
  1. pipeline position (per-stage: done/approved/pending, from T-320's gate
     records; current frozen version);
  2. spend: total vs `max_usd_per_run`, warn-threshold state, per-stage
     breakdown;
  3. open escalations (T-530) / halted reason, if any;
  4. progress list (as today).
- `harness log --project <dir> [--tail N] [--stage <name>]` — pretty-print
  run.log entries (timestamp, stage, model, template@version, tokens, cost)
  without the user parsing JSON lines.
- Aggregations tolerate a missing/partial run.log (fresh or pre-T-310
  projects) gracefully.

## Acceptance criteria
- After a fake pipeline run, `status` shows non-zero total spend equal to the
  sum of run.log entries, per-stage breakdown, and correct gate/stage
  positions.
- `log --tail 3 --stage tickets` prints exactly the last 3 tickets-stage
  entries, human-readable.
- Missing run.log → clean "no runs recorded" line, exit 0 (no traceback).
- `calls_by_template()` groups by (template, version) — verified with entries
  from two versions.

## Out of scope
- A/B statistics/comparison tooling (v1 — this ticket only exposes the
  grouping primitive).
- Web UI (v2).
- Writing run.log (T-310).

## Connections
- **Depends on:** T-050, T-230, T-310; richer with T-320, T-530.
- **Blocks:** prompt A/B tooling (v1).
- **Relates to:** T-510 (agent spend appears once unified).

## Testing
**Test-first** for the aggregation helpers (pure functions over entry lists);
CLI output via typer runner with a seeded journal.
