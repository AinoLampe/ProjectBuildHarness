# T-140 — Claude Code (`claude -p`) adapter

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/adapters/claude_code.py`

## Goal
Provide the single v0 implementation of `CodingAgentAdapter`, wrapping Claude
Code run headlessly via `claude -p`, so the implementation stage can write real
code and the review gate can run an isolated reviewer — both via the same adapter,
distinguished only by the arguments they receive (concept §10, §13).

## Creates / changes
- `adapters/claude_code.py` with two public entry points on a single class:

  **`run(workdir, prompt, sandbox) -> AgentResult`** — the implementer path.
  Spawns `claude -p` via `subprocess`, passing:
  - `--permission-mode dontAsk` (or `acceptEdits` where writes must be
    explicitly allowed) + an `--allowedTools` whitelist drawn from `sandbox`
    config (Read, Edit, Write, Bash for running tests, Glob, Grep).
  - `--model` from `config.models.implement`.
  - `--output-format json` so exit code + structured result + token usage can be
    parsed reliably.
  - Working directory confined to the project root (T-120 file confinement).

  **`review(ticket, diff_paths, criteria, objective_results, prompt) -> ReviewResult`**
  — the reviewer path. Spawns an entirely **separate** `claude -p` process:
  - Brand-new session (`query()` without `--resume`/`--continue`) — no shared
    context, no conversation history with the implementer.
  - `--permission-mode dontAsk` + `--allowedTools "Read,Glob,Grep"` only —
    can read and inspect, **never** write or run Bash.
  - `--model` from `config.models.review` (may be a stronger model).
  - Prompt assembled by the **orchestrator** (not by the implementer): concept
    path, guidelines path, the ticket file, the changed file paths, the
    objective results (tests/lint/types already ran), and the acceptance
    criteria. The reviewer never sees the implementer's conversation.
  - Requires a machine-parseable verdict in the response:
    `{"pass": bool, "reasons": [str]}`. If the response is not parseable,
    treat it as a reviewer failure (conservative default).

- `ReviewResult` dataclass: `passed: bool`, `reasons: list[str]`,
  `usage: TokenUsage`.

## Acceptance criteria
- `run()` passes the shared coding contract suite from T-130.
- `review()` passes a separate contract test confirming: fresh session (no
  `--resume`/`--continue`), read-only tools, `config.models.review` model,
  orchestrator-supplied prompt only, structured verdict returned.
- A gated smoke test exercises `run()` in a temporary project and produces a
  file change; a separate gated smoke test exercises `review()` on a real file
  and returns a parseable verdict.
- Honours sandbox file confinement from T-120.
- Captures usage/cost for both paths; wraps all failures as `AdapterError`.
- An unparseable reviewer response is surfaced as a failed review, not an
  exception that kills the pipeline.

## Design note — why a separate process, not a subagent
A fresh `claude -p` process starts a new session with no memory of prior turns.
This is the strongest available form of context isolation: the reviewer cannot
have seen the implementer's reasoning, only what the orchestrator explicitly
passes in. An in-session subagent shares the parent session's loaded context and
is invoked by the implementer — both properties we are trying to avoid.
Parallelism is free: separate processes share no state, so the orchestrator can
fan out `review()` calls with `asyncio.gather()` without any coordination.

## Out of scope
- OpenCode or any other agent (v1).
- Parallel branch execution for the *implementer* path (v2).
- Review-gate logic (which checks pass, retry loop, escalation) — that is T-200
  and T-210.

## Connections
- **Depends on:** T-130, T-120.
- **Blocks:** T-200, T-210 / real runs.
- **Relates to:** T-030 (model routing for both paths), T-090 (review prompt
  template assembled by orchestrator), T-050 (usage logged for both calls).

## Testing
**Test-after / contract + smoke.**
- `run()`: validated by T-130 contract suite + a Docker-gated smoke test.
- `review()`: a separate contract test (fresh session, read-only tools, structured
  verdict); a gated smoke test on a real file.
