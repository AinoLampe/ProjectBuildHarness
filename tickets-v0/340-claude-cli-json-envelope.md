# T-340 — Parse the real `claude -p --output-format json` envelope (usage, cost, verdict)

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/adapters/claude_code.py`,
`tests/contract/test_claude_code_adapter_contract.py`,
`tests/contract/test_claude_code_adapter_review.py`,
`tests/contract/test_claude_code_adapter_smoke.py`

## Problem
`ClaudeCodeAdapter` parses a JSON schema the real CLI does not emit. The real
`claude -p --output-format json` result is an envelope shaped like:

```json
{"type": "result", "subtype": "success", "is_error": false,
 "result": "<the agent's final text>", "session_id": "...",
 "total_cost_usd": 0.0123,
 "usage": {"input_tokens": 123, "output_tokens": 456, "...": "..."}}
```

The adapter instead reads **top-level** `success`, `input_tokens`,
`output_tokens`, `cost_usd`. Consequences against the real CLI:

1. `run()` reports usage `(0, 0)` and cost `0.0` for every call — the run log
   and any future budget accounting for Stage 3 are silently zero.
2. `review()` calls `_parse_json(completed.stdout)` and looks for `"pass"` in
   the **envelope** — but the reviewer's verdict JSON is inside the `result`
   string. Every real review therefore returns "unparseable verdict" →
   **every gate fails → every ticket retries then escalates**. The v0 pipeline
   cannot pass a single ticket against the real agent.

The fake-driven contract tests encode the invented schema (exactly the
"testing your own mocks" trap guidelines §4.2 warns about), and the review
smoke test asserts only `isinstance(result.passed, bool)` — vacuously true even
when parsing always fails (violates guidelines §4.4).

## Goal
The adapter speaks the real CLI's output contract, and the tests would fail if
it didn't.

## Creates / changes
- `claude_code.py`:
  - parse the envelope: success from `is_error`/`subtype`, usage from
    `usage.input_tokens`/`usage.output_tokens`, cost from `total_cost_usd`,
    summary from `result`.
  - `review()`: extract the verdict by parsing the **`result` text** (accept a
    fenced or bare JSON object within it); unparseable still → failed verdict.
  - verify `--permission-mode dontAsk` against the installed CLI version and
    switch to the supported non-interactive mode if it is not accepted
    (document the choice inline).
- Contract-test doubles updated to emit the **real envelope shape** (treat the
  envelope schema as the contract; source it from the current Claude Code
  docs at implementation time).
- Smoke tests strengthened: `review()` smoke asserts a *definitive* verdict on
  a case with a known expected outcome (e.g. a trivially compliant change must
  yield `passed=True`), not just a bool type check.

## Acceptance criteria
- Against a double emitting the real envelope: `run()` returns real usage +
  cost; `review()` extracts the verdict from `result`.
- Malformed envelope → `AdapterError` (run) / failed verdict (review), as
  today.
- Gated smoke tests confirm both paths against the installed CLI, with
  non-vacuous assertions.
- No test remains that asserts the old invented schema.

## Out of scope
- Streaming output (`--output-format stream-json`).
- Budget integration of the now-correct cost numbers (T-510).

## Connections
- **Depends on:** T-140.
- **Blocks:** T-510; any real (non-fake) Stage 3 run.
- **Relates to:** T-200, T-310.

## Testing
**Contract + smoke.** The updated contract suite is the spec; envelope fixtures
mirror real CLI output captured at implementation time.
