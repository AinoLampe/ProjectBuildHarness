# T-100 — TextStageAdapter protocol + contract suite + FakeTextAdapter

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/adapters/text.py`, `tests/contract/`,
`tests/fakes/`

## Goal
Define the seam that decouples the text stages (concept, guidelines, tickets)
from any provider, and ship the reference double the orchestration tests run
against (concept §13).

## Creates / changes
- `adapters/text.py` — `TextStageAdapter` Protocol:
  `generate(prompt, files) -> GenerationResult`, where `GenerationResult` carries
  the generated text **and** token usage (input/output) so the run log and budget
  guard have the numbers they need.
- `tests/contract/text_contract.py` — a shared behavioural suite any
  `TextStageAdapter` implementation must pass against a double.
- `tests/fakes/fake_text.py` — `FakeTextAdapter` returning scripted outputs +
  usage, passing the contract suite.

## Acceptance criteria
- The protocol is fully typed; `GenerationResult` exposes text + input/output
  token usage.
- The contract suite encodes the behavioural expectations (declared-file input,
  text + usage output, typed errors).
- `FakeTextAdapter` passes the contract suite and can script per-call outputs
  for stage/orchestration tests.

## Out of scope
- The real Anthropic implementation (T-110).
- The coding-agent seam (T-130).

## Connections
- **Depends on:** T-020, T-040.
- **Blocks:** T-110, T-160, T-170, T-180, T-190, T-240.
- **Relates to:** T-050 (usage logged), T-060 (usage feeds budget).

## Testing
**Contract-test driven.** The contract suite is the deliverable's spec;
`FakeTextAdapter` is validated by passing it.
