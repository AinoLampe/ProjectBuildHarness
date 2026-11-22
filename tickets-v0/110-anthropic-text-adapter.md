# T-110 — Anthropic text adapter

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/adapters/anthropic_text.py`

## Goal
Provide the single v0 implementation of `TextStageAdapter` using the Anthropic
Messages API, so the concept, guidelines, and ticket stages can run for real
(concept §13, §19 single provider).

## Creates / changes
- `adapters/anthropic_text.py` — wraps the Anthropic Messages API; resolves the
  model from config; injects the declared input files into the request; returns a
  `GenerationResult` with real text + token usage.
- Authentication via per-provider API key or the Claude subscription's
  non-interactive Agent SDK credit (note: **verify current pricing at run time**,
  concept §1).

## Acceptance criteria
- Passes the shared text contract suite from T-100.
- A network-gated smoke test (skippable offline) makes a real call and returns
  populated text + usage.
- Errors from the SDK are wrapped as `AdapterError`.
- Token usage is reported accurately enough to drive the budget guard and log.

## Out of scope
- Streaming.
- Any non-Anthropic provider (v1).
- The coding agent (T-140).

## Connections
- **Depends on:** T-100.
- **Blocks:** T-220 / real runs.
- **Relates to:** T-030 (model routing), T-060 (usage), T-050 (logging).

## Testing
**Test-after / contract + smoke.** Validated by the T-100 contract suite; a
separate, gated smoke test hits the live API (guidelines §4.2 — real adapters
smoke-tested separately).
