# T-710 — Thread each stage's real `max_tokens` into the pre-call budget headroom check

**Phase:** v1 — improvements (approved 2026-09-14)
**Module(s):** `src/harness/orchestrator.py`, `src/harness/cli.py`,
`src/harness/adapters/text.py`

## Problem
T-370 added `BudgetGuard.check_headroom(model, est_input_tokens, max_output_tokens)`
before every text-stage call, using `_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE = 4096`
"until T-420 makes max_tokens configurable per stage and threads the real value
through here". T-420 shipped `ModelRoute.max_tokens` and `cli.build_orchestrator`
passes it to each `AnthropicTextAdapter`, but the orchestrator's
`_RecordingTextAdapter` still uses the 4096 placeholder: a stage configured with
`max_tokens: 32000` (a whole epic plan or ticket set, T-640) is headroom-checked
against an eighth of its real worst case, so the pre-call guard can pass a call that
the post-call `record_usage` then rejects — after the spend.

## Goal
The headroom check uses the configured output ceiling of the stage being called.

## Creates / changes
- `adapters/text.py` — `DEFAULT_MAX_TOKENS` moves here from `anthropic_text.py`
  (re-exported there for compatibility) so the orchestrator needs no provider import.
- `orchestrator.py` — `_RecordingTextAdapter` gains `max_output_tokens: int`;
  `_wrap_text_adapter(inner, *, stage, model, max_output_tokens)` receives
  `config.models.<stage>.max_tokens or DEFAULT_MAX_TOKENS`;
  `_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE` deleted. The survey (T-610) and reviewer
  (T-650) paths are agent calls with self-reported cost and stay outside this check
  (docstring note).

## Acceptance criteria
- With `models.tickets.max_tokens: 32000` and a cap sized so that 4096 output tokens
  fit but 32000 do not, the tickets call raises `BudgetExceeded` **before** the adapter
  is invoked (the fake adapter records no call).
- Unset `max_tokens` → `DEFAULT_MAX_TOKENS` is used (identical to today's adapter
  default ceiling).
- No remaining reference to `_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE` (grep-clean).

## Out of scope
- Changing the chars/4 input estimate (`estimate_tokens_from_text`).
- Agent-stage headroom (self-reported cost model, T-510).

## Connections
- **Depends on:** T-600, T-310, T-370, T-420.
- **Blocks:** none.
- **Relates to:** T-640.

## Testing
**Test-first.** Cases: the configured ceiling reaches `check_headroom` (spy guard);
pre-call halt with no adapter call; default fallback.
