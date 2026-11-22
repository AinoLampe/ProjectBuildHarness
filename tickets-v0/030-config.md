# T-030 — Config model & loader

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/config.py`

## Goal
Parse and validate `harness.config.yaml` into a typed pydantic v2 model, with
defaults and clear errors, exposing per-stage model/agent routing and gate /
budget / sandbox / prompt policy to the rest of the harness (concept §4).

## Creates / changes
- `config.py` — pydantic v2 models mirroring concept §4:
  `project`, `models` (per-stage `{provider/agent, model}`), `gates`,
  `brainstorm`, `implementation` (incl. `review`, `retry_budget`, `on_exhaust`),
  `sandbox`, `budget`, `prompts`.
- YAML loader + validator returning the typed model.

## Acceptance criteria
- The sample config from concept §4 round-trips into the model.
- Malformed config (unknown stage, bad type, missing required field) raises
  `ConfigError` naming the offending field.
- Defaults are applied per concept/guidelines: gates `interactive`,
  `brainstorm.max_rounds=3` + `proceed_with_documented_assumptions`,
  `retry_budget=2` + `escalate_to_user`, budget caps, `phase_boundary: stop`.
- Per-stage routing is accessible (e.g. `config.models.concept`).
- For v0, `provider` is constrained to `anthropic` and `agent` to `claude-code`
  (the fields exist for v1, but other values are rejected with a clear message).

## Out of scope
- Using the routing to actually call providers (adapters/orchestrator own that).
- Multi-provider implementations (v1).

## Connections
- **Depends on:** T-010, T-020.
- **Blocks:** T-220 (orchestrator), T-230 (CLI).
- **Relates to:** T-110, T-120, T-140 (consume routing/sandbox settings).

## Testing
**Test-first.** Cases: valid round-trip; each malformed-config rejection;
defaults applied; v0 provider/agent constraint enforced.
