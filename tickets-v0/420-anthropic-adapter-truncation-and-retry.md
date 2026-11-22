# T-420 — Anthropic adapter: detect truncation, make max_tokens configurable, retry transients

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/adapters/anthropic_text.py`,
`src/harness/config.py`, `src/harness/orchestrator.py`, `src/harness/cli.py`

## Problem
1. **Silent truncation.** `AnthropicTextAdapter.generate()` never inspects the
   response's stop reason. With `DEFAULT_MAX_TOKENS = 4096`, a full concept
   document, a guidelines document, or — worst — the *entire ticket set in one
   response* (Stage 2 generates all tickets in a single call) will routinely
   hit the cap and be cut off mid-sentence. The truncated text flows straight
   into `concept.md`/tickets, gets gated, frozen, and built against. Nothing
   anywhere notices.
2. **`max_tokens` is not configurable.** 4096 is hard-coded as the default and
   `cli.build_orchestrator` constructs adapters without overriding it; no
   config field exists.
3. **No transient-error handling.** Any rate-limit/overload error aborts the
   whole run via `AdapterError`, even though these are the most common and
   most retriable failures in a long multi-call pipeline.

## Goal
Long generations either complete or fail loudly; transient provider errors
don't kill an unattended run.

## Creates / changes
- `anthropic_text.py`:
  - extend `_MessageLike` with `stop_reason`; when it is `max_tokens`, raise
    `AdapterError("response truncated at N output tokens …")` — never return
    truncated text as if complete. (A future continuation strategy may
    replace the error; failing loudly is correct now.)
  - bounded retry with exponential backoff (e.g. 3 attempts) for
    rate-limit/overload/5xx-classed SDK errors; other errors wrap immediately
    as today. Injected sleep for testability.
- `config.py` — optional `max_tokens` per `ModelRoute` (text stages only;
  default 4096 for compatibility... choose a larger default like 16384 for
  `tickets` in the sample config comment).
- `cli.py::build_orchestrator` — pass the configured `max_tokens` per stage.
- Contract suite (T-100) gains the truncation case so any future adapter must
  honour it.

## Acceptance criteria
- A fake client returning `stop_reason == "max_tokens"` → `AdapterError`
  naming truncation; normal `end_turn` unaffected.
- A fake client failing twice with a rate-limit error then succeeding →
  result returned, 3 calls observed, sleeps injected not real.
- A non-transient error → `AdapterError` on the first attempt (no retry).
- `models.tickets.max_tokens: 16384` in config reaches the adapter.

## Out of scope
- Streaming (v1).
- Continuation/auto-resume of truncated generations.
- Multi-provider adapters (v1).

## Connections
- **Depends on:** T-030, T-100, T-110, T-230.
- **Blocks:** reliable real (non-fake) text-stage runs.
- **Relates to:** T-370 (max_tokens ceiling feeds the pre-call headroom
  check), T-500 (structured outputs shrink response sizes).

## Testing
**Contract + unit.** Truncation and retry cases via injected fake clients;
config plumbing via a build_orchestrator unit test.
