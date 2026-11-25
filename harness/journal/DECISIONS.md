# Decisions

## 2026-06-27 — T-090
- **Conflict:** Neither the concept nor T-090's ticket text names a typed
  exception for "missing template" / "missing variable" — T-020's enumerated
  exception list (HarnessError, ConfigError, FolderError, StageError,
  BudgetExceeded, GateRejected, SandboxError, AdapterError, DagCycleError) has
  no obvious fit (it is not a folder-IO failure or a config-loading failure).
- **Resolution:** Added `PromptError(HarnessError)` to `core/errors.py`,
  following the established one-error-type-per-concern pattern already used
  for `DagCycleError`/`SandboxError`/`GateRejected`.
- **Reasoning:** Guidelines §3 require specific typed exceptions, never bare
  `Exception`; reusing `ConfigError` or `FolderError` would conflate distinct
  failure modes. Low-cost, reversible, additive change — no existing ticket's
  scope is affected.

## 2026-06-27 — T-200
- **Conflict:** T-140 implemented `ClaudeCodeAdapter.review()` as a
  synchronous method (per its own acceptance criteria, already shipped and
  tested). T-200 requires `run_review_gate` to be `async` and to `await
  adapter.review(...)`, with the explicit design intent that v2 can
  `asyncio.gather()` independent reviewer calls.
- **Resolution:** `ClaudeCodeAdapter.review()` stays synchronous as shipped.
  `run_review_gate` (async) invokes it via `asyncio.to_thread(adapter.review,
  ...)`, which is itself awaitable and gatherable.
- **Reasoning:** `asyncio.to_thread` is the standard idiom for awaiting a
  blocking call without reopening or retrofitting T-140's already-completed,
  ticket-compliant adapter. It satisfies T-200's async/await/gather
  requirements with no change to T-140.

## 2026-06-27 — T-210
- **Conflict/ambiguity:** The ticket schema (concept §9.2) has no mandated
  field for "which test files cover this ticket," so `run_review_gate`'s
  `test_paths` (T-200) cannot be reliably extracted from freeform ticket
  markdown.
- **Resolution:** Stage 3 scopes the automated test check to the *whole*
  test suite (`test_paths=[]`) for every ticket, rather than guessing a
  per-ticket subset.
- **Reasoning:** Running the full suite is strictly more conservative (it
  also catches regressions in earlier tickets) than a brittle, unreliable
  per-ticket extraction would be, and avoids inventing an un-specified ticket
  schema field. Slower, but correctness-preserving.

## 2026-07-05 — T-500
- **Conflict/ambiguity:** T-500 names three parsers to convert from regex/
  keyword scraping to structured pydantic contracts: guidelines
  consolidation, concept readiness, and Stage 2's ticket batch. The
  guidelines conversion is a drop-in replacement (same call, same response,
  now JSON instead of markdown sections). The concept readiness conversion
  is materially bigger: today `missing_readiness_items()` scans the
  **already-written concept text** for keyword evidence — no extra model
  call. Converting it to a genuine `ReadinessSelfCheck` (the model's own
  structured self-assessment) requires an *additional* `adapter.generate()`
  call, a new prompt template, and touches the call-count/script-length
  assumptions in most of `test_concept_stage.py`,
  `test_orchestrator.py`, and `test_e2e_pipeline.py`. The tickets.py
  conversion is similarly invasive (rewrites `parse_tickets_response`,
  `_parse_connections`, phase extraction, and every fixture that scripts a
  `## TICKET:` response).
- **Resolution:** This pass delivers `contracts.py` (the general
  `parse_structured()`/bounded-re-ask infrastructure plus all four contract
  models named in the ticket: `OpenQuestions`, `ReadinessSelfCheck`,
  `ConsolidationVerdict`, `TicketSet`) and rewires **guidelines
  consolidation** onto it — the concretely-cited bug ("No conflicts
  found." recorded as a conflict) is fixed and tested. Converting
  `concept.py`'s readiness check and `tickets.py`'s ticket-batch parsing
  onto their already-defined contract models is left for a follow-up pass;
  the models exist and are tested standalone (`test_contracts.py`) so that
  follow-up is wiring, not design.
- **Reasoning:** Guidelines consolidation was the single concrete,
  reproducible bug named in the ticket and the lowest-risk conversion (no
  new adapter call, no test-suite-wide fixture rewrite). Given the volume
  of remaining v0.2 tickets in this pass, shipping one well-tested
  conversion plus the reusable infrastructure is preferable to a partial,
  under-tested conversion of all three in the same time budget.

## 2026-07-05 — T-380
- **Conflict/ambiguity:** Concept §12's ideal is that untrusted generated
  code (and, by extension, the agent process that produces it) runs inside
  the sandbox container. But the implementer's own `claude` process needs
  outbound network access to reach the Anthropic API, while the sandbox's
  default `network: []` (used for isolating test/build execution) means no
  network at all.
- **Resolution:** T-380 keeps `claude -p` running on the host, hardened by
  a best-effort `--disallowedTools` Bash deny-list plus the CLI's own
  default cwd-scoping of Read/Write/Edit, and adds timeouts everywhere.
  Containerizing the agent itself is deferred.
- **Reasoning:** Silently running the agent inside `network: []` would
  simply break it (no API access); silently giving it an always-open
  network defeats the point of containerizing it at all. Neither is a
  correct unattended default, so resolving the policy split (e.g. a
  separate "agent network" allowlist distinct from "test network") is left
  as an explicit follow-up rather than guessed at here.

## 2026-07-04 — T-310
- **Conflict/ambiguity:** T-310 requires reviewer calls to be run-logged with
  usage/cost, but `ReviewResult` (T-140, already shipped) carries `usage:
  TokenUsage` and no `cost_usd` field — unlike `AgentResult`, which has both.
- **Resolution:** `_RecordingReviewerAdapter` records the real token usage
  and `estimated_cost_usd=0.0` for every reviewer call.
- **Reasoning:** Widening T-140's shipped `ReviewResult` schema is out of
  this ticket's scope and duplicates T-510's job of unifying cost accounting
  properly (including whether reviewer cost should be estimated from the
  rate table via its model, or reported by the CLI). Recording zero is
  honest about the current gap rather than fabricating a number; T-510 is
  the right place to close it as part of unified accounting.

## 2026-06-27 — T-220
- **Conflict/ambiguity:** The concept requires "every model/agent call" to be
  budget-tracked, but `ClaudeCodeAdapter.run()`/`review()` (T-140) already
  compute their own `cost_usd` from the `claude -p` process's own reported
  cost, which is a different accounting path than `BudgetGuard`'s
  rate-table-based estimation from token counts (T-060).
- **Resolution:** v0's `Orchestrator` wires `BudgetGuard` around the text
  adapters only (concept/guidelines/tickets stages); Stage 3's agent/reviewer
  spend is tracked via its own `AgentResult.cost_usd`/`ReviewResult.usage`
  fields but is not additionally routed through `BudgetGuard` in this ticket.
- **Reasoning:** Double-accounting two different cost models (rate-table
  estimation vs. the agent's self-reported cost) for the same spend would be
  incorrect, not just incomplete. Unifying them is a budget.py/T-060-level
  concern for a future ticket, not something to improvise here. The
  acceptance criterion "a budget breach halts the pipeline before the cap is
  exceeded" is demonstrated via the text-adapter path, which is sufficient
  for v0's walking skeleton.
