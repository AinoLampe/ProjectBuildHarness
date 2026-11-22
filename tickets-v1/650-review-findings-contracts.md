# T-650 — Structured review findings: `Finding`/`ReviewFindings` contracts; the reviewer returns a ledger with real cost

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `src/harness/contracts.py`, `src/harness/adapters/claude_code.py`,
`src/harness/stages/review.py`, `src/harness/orchestrator.py`
(`_RecordingReviewerAdapter`), `src/harness/prompt_templates/v1/` (`review_gate.md`,
`final_acceptance.md`; `review_proposals.md` new)

## Motivation
R5.3 asks the review agent (RA) for "a structured review artefact with findings-ids".
Today the verdict is `{"pass": bool, "reasons": [str]}` pulled out of the `claude -p`
result text by a regex (`_VERDICT_OBJECT_RE` in `claude_code.py`) — no ids, no
severity, no location, no way to say "F-003 is now resolved" or "your argument on
F-002 is accepted". The implementer cannot respond per finding (R5.4) and an escalation
cannot list what is still open (R5.5). Separately, `ReviewResult` carries no
`cost_usd`, so every reviewer call is booked at $0 (DECISIONS.md T-310) although the
envelope reports `total_cost_usd`.

## Goal
The RA's output is a validated findings ledger with stable ids, severities, locations
and statuses, produced by a fresh read-only process, with usage and real cost — the
data model the dialogue loop (T-660), the epic gate (T-670) and escalation proposals
build on (concept v1.1 §10.3).

## Creates / changes
- `contracts.py` —
  - `Severity = Literal["blocker","major","minor","nit"]`; `FindingStatus =
    Literal["open","resolved","declined_accepted","declined_rejected"]`.
  - `Finding(id: str, severity: Severity, category: str (correctness |
    acceptance-criteria | out-of-scope | guidelines | tests | security | drift |
    other), location: str ("path:line" or "path"), description: str,
    required_action: str, status: FindingStatus = "open", note: str = "")`. Id shape
    `F-NNN`; synthetic `F-OBJ-N` (objective checks) and `F-RPT-N` (report problems).
  - `ReviewFindings(round: int, verdict: Literal["pass","changes_requested"],
    findings: list[Finding], summary: str)` — the **full ledger** each round: prior
    findings with updated status plus new ones. `validate_verdict(blocking:
    set[Severity])`: `pass` with an `open`/`declined_rejected` finding of a blocking
    severity is downgraded to `changes_requested` with a `note` (never silently
    accepted).
  - `Proposal(id: int, title: str, description: str, action:
    Literal["accept_argument","waive","split_ticket","change_approach",
    "amend_criteria","other"], finding_ids: list[str])`;
    `EscalationProposals(proposals: list[Proposal])` (≥ 2).
  - `synthetic_objective_findings(objective: ObjectiveResult) -> list[Finding]` (one
    `blocker` per failing check; the output tail as description).
- `adapters/claude_code.py` — `ReviewResult` becomes `ReviewResult(findings:
  ReviewFindings, usage: TokenUsage, cost_usd: float)` with derived properties
  `passed` (verdict == pass) and `reasons` (open findings rendered `"F-001 [major]
  path:line — description"`), so `ReviewerVerdictLike` consumers keep working;
  `review()` delegates to `inspect()` (T-610) and parses the result text with
  `parse_structured(text, ReviewFindings)`; unparseable → `ReviewFindings(verdict=
  "changes_requested", findings=[F-RPT-1 blocker "reviewer output was not a valid
  ReviewFindings JSON object"])` — **no re-ask process** (the next round re-invokes
  the RA anyway); `cost_usd` from `total_cost_usd`. `_VERDICT_OBJECT_RE` and
  `_extract_verdict` deleted.
- `stages/review.py` — `ReviewerVerdictLike` gains `findings: ReviewFindings`;
  `run_review_gate(...)` gains `round_number: int = 1`, `prior_findings:
  ReviewFindings | None = None`, `resolution_report: str = ""` (rendered markdown),
  `blocking_severities: set[Severity]`; objective red → `GateResult(passed=False,
  findings=<synthetic ledger>, llm_verdict=None)` with no RA call; `GateResult` gains
  `findings`. `review_gate.md` gains `{{round_number}}`, `{{prior_findings}}`,
  `{{resolution_report}}`, `{{blocking_severities}}` and the round rules: round 1 —
  review everything; round > 1 — first re-evaluate every prior finding (`resolved`,
  still `open`, or for a declined one: accept the argument → `declined_accepted`, or
  reject it → `declined_rejected` with a `note`), then add new findings **only** on
  code changed since the last round or of severity ≥ major; keep ids stable; output
  the full ledger as one JSON object.
- `final_acceptance.md` — demands the same `ReviewFindings` schema (category `drift`);
  `ImplementStage`'s final pass consumes `verdict`/`findings` (summary text derived as
  today; escalation kind `drift` unchanged).
- `review_proposals.md` (new) — given the ticket, the final ledger and the last
  resolution report, produce `EscalationProposals` JSON (≥ 2 concrete proposals, each
  tied to finding ids, each actionable by a human in one sentence). Used by T-660;
  template and contract land here so the schema is complete.
- `orchestrator.py` — `_RecordingReviewerAdapter` routes `result.cost_usd` (no longer
  0.0) into the budget ledger and run.log.
- Fakes/tests — the test-side `FakeReviewerAdapter` scripts `ReviewFindings`; contract
  fixtures emit the real envelope with a findings JSON in `result`.

## Acceptance criteria
- A valid ledger parses to `ReviewResult.findings`; `passed`/`reasons` derive
  correctly; a `pass` with an open `minor` stands; a `pass` with an open `major` is
  downgraded to `changes_requested` with a note.
- Unparseable reviewer output → `changes_requested` with synthetic `F-RPT-1`; no second
  process spawned (runner call count 1).
- Objective checks red → synthetic `F-OBJ-*` blockers and `adapter.review` never
  called (existing behaviour, now structured).
- The round > 1 prompt contains the prior ledger, the resolution report and the round
  rules; the round 1 prompt carries no ledger (template render assertions).
- Reviewer `cost_usd` from the envelope reaches `BudgetGuard` and run.log (previously
  0.0).
- The final acceptance pass parses the findings schema; drift is reported as findings
  and still surfaces as a run-level `drift` escalation and CLI warning (T-410 tests
  updated, not weakened).
- Behaviour of every `ReviewerVerdictLike` consumer (`GateResult.llm_verdict`,
  orchestrator warnings) is unchanged.

## Out of scope
- The round loop, resolution-report production and per-round persistence (T-660).
- Epic reviews (T-670).
- Which model reviews (config unchanged).

## Connections
- **Depends on:** T-600, T-610, T-140, T-200, T-340, T-410, T-500, T-510.
- **Blocks:** T-660, T-680.
- **Relates to:** T-310, T-550, T-670.

## Testing
**Test-first** for the contracts (validators, synthetic findings, derived properties)
and `run_review_gate` (round variables, red short-circuit); **contract tests** for
`review()`/`inspect()` (envelope, findings parsing, unparseable path, no
`--resume`); consistency test extended for the three templates.
