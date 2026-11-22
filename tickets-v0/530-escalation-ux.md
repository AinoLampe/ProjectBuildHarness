# T-530 — Escalation UX: a stuck run must hand back a resumable, actionable state

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/journal.py`, `src/harness/stages/implement.py`,
`src/harness/orchestrator.py`, `src/harness/cli.py`

## Motivation
Concept §20 lists "the exact escalation UX (how a stuck ticket is surfaced and
handed back)" as an open item, and today it shows: retry-budget exhaustion
raises `StageError` whose message-with-embedded-reasons surfaces as a Python
traceback from the CLI; ambiguity escalation (`concept §10.1: "escalated to
the user before proceeding"`) has no channel at all; `blocking_questions` are
discarded by the orchestrator. For a tool whose core promise is *unattended
operation with human checkpoints where they matter*, "the checkpoint" being a
stack trace is the weakest part of the product.

## Creates / changes
- `journal.py` — `EscalationRecord` (timestamp, ticket, kind:
  `retry_exhausted | ambiguity | drift | budget`, context: gate reasons /
  question text / failing output tail, and `resolution: str | None`), with
  the standard md + JSON mirror pair (`journal/ESCALATIONS.md` /
  `escalations.json`).
- `implement.py` — on retry exhaustion: write the record (full gate reasons,
  last objective-check output tail, attempt count), then raise a new
  `EscalationRequired(HarnessError)` carrying the record.
- `orchestrator.py` — catch `EscalationRequired`, return a halted
  `OrchestratorResult` with `halt_reason="escalation"` (no traceback);
  unresolved `blocking_questions` from any stage become escalation records
  too.
- `cli.py`:
  - `run` prints a compact escalation summary (ticket, why, the top reasons,
    "how to resume") and exits with a dedicated code.
  - `status` shows open escalations first.
  - `harness resolve --project <dir> --escalation <id> --answer <text>`
    records the human's resolution; the next `run` re-attempts the escalated
    ticket with the resolution injected into its prompt (fresh retry
    budget).

## Acceptance criteria
- Retry exhaustion: no traceback; CLI prints ticket id + reasons + resume
  hint; exit code distinct from config/gate errors; `ESCALATIONS.md` entry
  complete enough to act on without reading logs.
- `harness resolve` + re-run: the escalated ticket is retried with the
  resolution text in its prompt and a fresh budget (fake-proven).
- A run with an unresolved escalation refuses to re-attempt that ticket
  (no silent thrash) until resolved.
- `status` lists open escalations before progress.

## Out of scope
- Web/notification channels (v2).
- Gate rejection flow (T-320 — related but distinct checkpoint).

## Connections
- **Depends on:** T-050, T-210, T-220, T-230.
- **Blocks:** none.
- **Relates to:** T-320, T-410 (drift as an escalation kind), T-510 (budget
  halt as an escalation kind).

## Testing
**Test-first.** Cases: exhaustion → record + clean halt + exit code;
resolve → re-attempt with injected resolution; unresolved → no re-attempt;
status ordering.
