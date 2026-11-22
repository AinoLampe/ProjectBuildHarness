# T-740 — Run the coding agent inside the sandbox: agent-network allowlist + in-container `claude -p`

**Phase:** v1 — improvements (approved 2026-09-14)
**Module(s):** `src/harness/sandbox.py`, `src/harness/adapters/claude_code.py`,
`src/harness/config.py`, `src/harness/cli.py`

## Problem
Concept §12 wants untrusted generated code — and by extension the agent producing it —
isolated in a container. T-380 left `claude -p` on the host behind a best-effort
`--disallowedTools` Bash deny-list because the sandbox's single `network: []` policy
(built for offline test execution) would cut the agent off from the Anthropic API
(DECISIONS.md T-380). The residual risk is documented: a confused or prompt-injected
agent — it reads project files an attacker may have written, which R1's
existing-project mode makes routine — can run any Bash the deny-list does not match,
on the host, with the user's credentials in the environment.

## Goal
Two network policies (tests offline by default; the agent allowed to reach its API)
and an opt-in mode that runs the agent process inside the container, so file
confinement and code execution are enforced by the container rather than by pattern
matching (concept v1.1 §12).

## Creates / changes
- `config.py` — `SandboxConfig.agent_network: list[str] = ["api.anthropic.com"]`;
  `SandboxConfig.agent_in_container: bool = False` (opt-in until the image is
  validated); `SandboxConfig.agent_env_passthrough: list[str] = ["ANTHROPIC_API_KEY"]`.
- `sandbox.py` — `build_docker_command(command, *, network: list[str] | None = None,
  env: list[str] | None = None)`: `network` overrides the instance policy for this
  invocation (`[]` → `--network none`; non-empty → the default bridge network,
  best-effort as today — true per-domain allowlisting stays a §20 open item, now
  scoped to "a proxy or DNS filter in the image"); `env` → `-e KEY` passthrough (the
  value is taken from the host environment by Docker, never placed in the argv or
  logged); `run_agent(argv, *, env)` executes with `agent_network`.
- `adapters/claude_code.py` — when `agent_in_container` is set, `run()`, `inspect()`
  and `review()` invoke `sandbox.run_agent([...claude argv...], env=passthrough)` with
  cwd `/workspace` (the mount path) instead of the host `process_runner`; the
  deny-list stays (defence in depth); `command_timeout_s` applies to the Docker
  invocation. Document the image requirement (a `claude` binary in
  `harness/devcontainer`; the concept §20 image item).
- `cli.py` — `build_orchestrator` wires the new fields; `status` prints the sandbox
  mode.

## Acceptance criteria
- `build_docker_command` with `network=["api.anthropic.com"]` omits `--network none`
  and includes `-e ANTHROPIC_API_KEY` without a value; with `network=[]` it includes
  `--network none`.
- `agent_in_container: true` → the adapter builds a `docker run … claude -p …` argv
  (unit-tested through the injected runner; no Docker executed), the working directory
  inside the container is the mount path, and `--disallowedTools` is still present;
  `false` → today's host invocation, byte-identical argv.
- Test-execution sandbox commands are unaffected by `agent_network` (still `--network
  none` by default).
- Gated smoke test (Docker + image + `claude` available) runs a trivial `inspect()`
  in-container.

## Out of scope
- Enforcing the domain allowlist inside the container (proxy/DNS — §20).
- Subscription (non-API-key) authentication passthrough.

## Connections
- **Depends on:** T-600, T-120, T-140, T-380.
- **Blocks:** none.
- **Relates to:** T-610, T-650, T-700.

## Testing
**Test-after / contract** for command construction (pure), the adapter argv under both
modes, env passthrough without value leakage; gated smoke test.
