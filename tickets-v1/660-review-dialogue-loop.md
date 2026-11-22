# T-660 — Review dialogue: bounded implementer ↔ reviewer rounds with resolution reports, a findings ledger, and escalation with proposals

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `src/harness/stages/implement.py`, `src/harness/journal.py`,
`src/harness/folder.py`, `src/harness/config.py`, `src/harness/cli.py`,
`src/harness/contracts.py` (`ResolutionReport`), `src/harness/prompt_templates/v1/`
(`implement_bootstrap.md`; `implement_round.md` new; `implement_retry.md` retired)

## Motivation
R5 specifies the per-ticket process: the implementation agent (IA) delivers code
**and a resolution report**; the orchestrator sends both, with the ticket, to a
separately spawned review agent (RA); the RA returns findings with ids; the IA answers
each finding by fixing or arguing, recording every action against the finding id in
its resolution report; and so on until a configurable maximum, then escalation to a
human **with proposals**. Today `_implement_one_ticket` re-runs the IA with
`implement_retry.md` ("your previous attempt failed for: …") wrapping the previous
prompt — so the prompt nests once per retry — the IA's only output is the CLI's final
text, nothing is persisted per round, the IA cannot decline a finding, and the
escalation context is a joined string of reasons with no options for the human.
Session model decided 2026-09-14: **fresh IA and RA processes every round** — the files
under `journal/tickets/<id>/` are the memory (concept principle 1), which also makes a
round crash-resumable (concept v1.1 §10.3–§10.4, §16).

## Goal
Per unit, a bounded loop of rounds — IA turn (code + `ResolutionReport`) → objective
checks → RA turn (`ReviewFindings`) — persisted round by round, ending in `pass` or an
escalation record that carries the open ledger and concrete proposals a human can pick
with one command.

## Creates / changes
- `contracts.py` — `ResolutionReport(round: int, summary: str, changed_files:
  list[str], deviations: list[str], decisions: list[DecisionItem],
  finding_responses: list[FindingResponse], open_questions: list[str])`;
  `DecisionItem(conflict, resolution, reasoning)`; `FindingResponse(finding_id: str,
  action: Literal["fixed","partially_fixed","declined"], explanation: str)`.
  `validate_against(prior: ReviewFindings | None)`: every prior finding that was
  `open` or `declined_rejected` must have a response — a missing one is added as
  `declined` with the explanation "(no response given)" and flagged, so the RA sees
  it.
- `config.py` — `ImplementationConfig.max_review_rounds: int = 3` (rounds per unit).
  **`retry_budget` becomes a deprecated alias:** set alone → `max_review_rounds =
  retry_budget + 1` plus a deprecation warning through `on_warning`; both set →
  `ConfigError`. `blocking_severities: list[Severity] = ["blocker","major"]`.
- `folder.py` — `journal_tickets_dir`, `journal_unit_dir(unit_id)`
  (`journal/tickets/<T-0NN>/`; T-670 maps epic units to `journal/epics/<E0N>/`),
  `journal_round_paths(unit_id, round) -> RoundPaths` (`round-NN-resolution.json`
  / `.md`, `round-NN-review.json` / `.md`).
- `journal.py` — `record_round(folder, unit_id, round, report: ResolutionReport |
  None, findings: ReviewFindings)` writes the four files (markdown rendered from the
  structures, JSON via `write_json_atomic`); `read_rounds(folder, unit_id) ->
  list[RoundRecord]`; `latest_round(...)`. `EscalationRecord` gains `ledger:
  list[Finding] = []` and `proposals: list[Proposal] = []` (append-only semantics
  unchanged); `ESCALATIONS.md` renders the open findings and the numbered proposals.
  `ProgressEntry` gains `rounds: int = 0`; `deviations` is filled from the final
  report.
- `stages/implement.py` — `_implement_one_ticket` becomes `_run_dialogue(unit_id,
  prompt_builder, …)`, reused by T-670:
  1. **Resume.** If `journal_unit_dir(unit_id)` holds a completed round N whose
     verdict was `changes_requested`, continue at N+1 with the ledger from disk
     (fresh process).
  2. **IA turn.** Round 1 → `implement_bootstrap.md` (existing inputs plus: "finish
     with exactly one JSON object matching `ResolutionReport` as your final message;
     do **not** write `DECISIONS.md` yourself — put decisions in the report"; the
     `{{journal_dir}}` variable is dropped); round > 1 → `implement_round.md`
     (`{{ticket_id}}`, `{{ticket_text}}`, `{{ledger}}` — open and `declined_rejected`
     findings rendered with ids —, `{{previous_report}}`, `{{round_number}}`,
     `{{max_rounds}}`, the source-of-truth paths; rule: "for every listed finding
     either fix it or decline it with a concrete reason; never silently ignore one").
     The report is parsed from `AgentResult.summary` with `parse_structured`;
     missing or invalid → the round proceeds with `report=None` and a synthetic
     `F-RPT-1` (major) is added to the ledger (no re-ask process). The orchestrator
     writes the report's `decisions` to `DECISIONS.md` (single writer). A non-empty
     `open_questions` → `record_escalation(kind="ambiguity", ticket=unit_id,
     context=<questions>)` and `EscalationRequired` **before** the RA turn (concept
     §10.1: never guess); a resolution restarts the unit at round 1 with a fresh cap.
  3. **Objective checks** (T-520 scoping) → red: synthetic `F-OBJ-*` blockers, round
     recorded, **no RA call**, next round.
  4. **RA turn** via `run_review_gate(..., round_number, prior_findings,
     resolution_report)`; round recorded via `record_round`.
  5. `pass` → `record_progress(rounds=N, deviations=…)`; done. Else if `N ==
     max_review_rounds` → proposals call (`review_proposals.md` through the reviewer
     adapter's `inspect()`, parsed to `EscalationProposals`; unparseable → the fixed
     fallback list: accept the IA's arguments / waive remaining non-blockers / split
     the ticket / retry with a different approach / amend the acceptance criteria),
     then `record_escalation(kind="review_exhausted", ticket=unit_id, ledger,
     proposals)` and raise `EscalationRequired`.
  6. A resolved escalation (T-530) restarts the unit at round 1 with a fresh cap and
     the human's answer or chosen proposal rendered into the IA prompt as today.
- `cli.py` — `harness resolve --ticket <unit> --choose N` records proposal N's title
  and description as the resolution (mutually exclusive with `--answer`); `status`
  shows per unit: rounds used, open and declined-rejected finding counts; the
  escalation summary printed by `run` lists the numbered proposals.
- Templates — `implement_bootstrap.md` (report instruction; no self-written
  `DECISIONS.md`; `{{journal_dir}}` removed), `implement_round.md` (new),
  `implement_retry.md` removed from `NAMED_TEMPLATES` and deleted. Consistency test
  extended.

## Acceptance criteria
- Fake-scripted ticket: round 1 IA report + RA `changes_requested` (F-001 major, F-002
  minor) → round 2 IA report answers `fixed` for F-001 and `declined` for F-002 → RA
  marks F-001 `resolved`, F-002 `declined_accepted` → `pass`.
  `journal/tickets/T-010/` holds `round-01-*` and `round-02-*` (json + md); `PROGRESS`
  has `rounds: 2`; the report's `decisions` appear in `DECISIONS.md` written by the
  harness; no IA prompt instructs the agent to write `DECISIONS.md`.
- `max_review_rounds: 2` with a perpetually failing RA: exactly 2 IA calls, 2 RA calls,
  1 proposals call; `ESCALATIONS.md` lists the open ledger and ≥ 2 numbered
  proposals; clean halt, exit code 5.
- Objective-red round: no RA call, synthetic `F-OBJ` blockers in the recorded ledger,
  the round counts toward the cap.
- Crash after round 1 was recorded: a new stage run resumes at round 2 with the ledger
  from disk (fake asserts the round-2 prompt content) and does not repeat round 1.
- `harness resolve --choose 2` records proposal 2's text; the next run starts at
  round 1 with it in the prompt and a fresh cap; `--choose` and `--answer` together →
  exit 1.
- Missing or invalid IA report → `F-RPT-1` in the RA prompt; the loop continues.
- IA `open_questions` → `ambiguity` escalation before any RA call.
- `retry_budget: 2` alone maps to `max_review_rounds: 3` with a warning; both set →
  `ConfigError`.
- Every IA and RA call is a fresh process: no `--resume`/`--continue` in any command
  (adapter contract test) and no round prompt embeds a previous prompt.

## Out of scope
- Epic units and the epic gate (T-670 reuses `_run_dialogue`).
- Resuming agent sessions (decided against).
- Parallel units (v2).

## Connections
- **Depends on:** T-600, T-650, T-210, T-400, T-520, T-530.
- **Blocks:** T-670.
- **Relates to:** T-380, T-410, T-560.

## Testing
**Test-first** for the loop (a state machine over scripted rounds), report validation,
round persistence and resume, escalation record content, the config alias; CLI via
`CliRunner`; fakes: `FakeCodingAgent` results carry the report JSON in `summary`, the
test-side `FakeReviewerAdapter` scripts ledgers, a `FakeInspector` scripts proposals.
