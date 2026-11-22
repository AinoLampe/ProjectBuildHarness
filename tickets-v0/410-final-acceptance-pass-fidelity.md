# T-410 — Final acceptance pass: templated prompt, read-only validation, surfaced result

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/stages/implement.py`,
`src/harness/orchestrator.py`, `src/harness/prompt_templates/v1/`,
`src/harness/cli.py`

## Problem
Concept §10.6's closing-the-loop pass is implemented three ways short of the
spec:

1. **Hard-coded prompt.** The final-acceptance prompt is an f-string inside
   `ImplementStage.run()`, violating concept §15 ("every injected prompt is a
   versioned template … never a hard-coded string"). The retry-feedback
   prompt in `_implement_one_ticket` is likewise ad-hoc string surgery.
2. **Wrong tool for validation.** The pass calls `adapter.run()` — the
   implementer path with **write** tools — for what is a read-and-judge task.
   A validator that can silently "fix" what it is judging is not a validator;
   the reviewer path (read-only, fresh session, `models.review`) is the
   right seam.
3. **The result goes nowhere.** `ImplementStage` surfaces drift via
   `StageResult.blocking_questions`, but `Orchestrator._run_implement()`
   discards the return value entirely, and the CLI prints nothing. §10.6's
   "then a confirmation prompt is sent to the user" does not exist — drift is
   detected and then dropped on the floor.

## Goal
The final pass is a templated, read-only review of the assembled
implementation against `requirements.md`, and its outcome reaches both the
journal and the user.

## Creates / changes
- `prompt_templates/v1/final_acceptance.md` — new template (requirements,
  frozen concept, instruction to report drift as a structured verdict);
  registered in `prompts.NAMED_TEMPLATES`.
- `prompt_templates/v1/implement_retry.md` — template for the
  retry-with-review-feedback prompt (`{{original_prompt}}`, `{{reasons}}`).
- `implement.py` — final pass rendered from the template and executed via the
  **reviewer** adapter (`adapter.review`-style read-only path); drift verdict
  recorded in the journal (decision/progress entry) and returned in
  `StageResult.blocking_questions` as today.
- `orchestrator.py` — consume `StageResult` from `_run_implement`; include a
  drift summary in `OrchestratorResult` (e.g. `warnings: list[str]`).
- `cli.py` — print the drift/confirmation summary after `run`; non-empty
  drift → distinct exit code (documented) so scripts can react.

## Acceptance criteria
- No hard-coded prompt strings remain in `implement.py` (both new templates
  used; grep-clean).
- The final pass never invokes the write-capable implementer path (fake
  proves `run()` is not called for it).
- A fake-scripted drift verdict lands in the journal, in
  `OrchestratorResult`, and in CLI output with the documented exit code.
- No drift → normal success output, exit 0.

## Out of scope
- Structured-output schema for the verdict (T-500 refines the format).
- Prompt content optimisation (T-550).

## Connections
- **Depends on:** T-090, T-200, T-210, T-220, T-230.
- **Blocks:** none.
- **Relates to:** T-500, T-550, T-340 (verdict extraction).

## Testing
**Test-first.** Cases: template rendered with both variables; reviewer-path
invocation; drift propagation journal→result→CLI; retry prompt from template.
