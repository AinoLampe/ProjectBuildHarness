# T-130 — CodingAgentAdapter protocol + contract suite + FakeCodingAgent

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/adapters/coding.py`, `tests/contract/`,
`tests/fakes/`

## Goal
Define the seam between the orchestrator and the coding agent (the
implementation stage), and ship the reference double that lets the full pipeline
be tested without a real agent or spend (concept §13, guidelines §4.3).

## Creates / changes
- `adapters/coding.py` — `CodingAgentAdapter` Protocol:
  `run(workdir, prompt, sandbox) -> AgentResult`, where `AgentResult` carries the
  outcome plus usage/cost. References the `Sandbox` type from T-120.
- `tests/contract/coding_contract.py` — shared behavioural suite any
  implementation must pass.
- `tests/fakes/fake_coding.py` — `FakeCodingAgent` that simulates writing `src/`
  and journal entries from a script, passing the contract suite.

## Acceptance criteria
- Protocol fully typed; `AgentResult` exposes outcome + usage/cost.
- The contract suite encodes expected behaviour (runs in the given workdir under
  the given sandbox; returns outcome + usage; typed errors).
- `FakeCodingAgent` passes the suite and can script file writes + per-ticket
  results so the orchestrator and Stage 3 can be exercised without a real agent.

## Out of scope
- The real `claude -p` implementation (T-140).
- Review-gate semantics (T-200) and the Stage 3 driver loop (T-210).

## Connections
- **Depends on:** T-020, T-040, T-120.
- **Blocks:** T-140, T-160, T-200, T-210, T-240.
- **Relates to:** T-050, T-060 (usage/cost).

## Testing
**Contract-test driven.** The contract suite is the spec; `FakeCodingAgent` is
validated by passing it.
