# T-380 — Sandbox gaps: the implementer agent runs unconfined on the host; no timeouts

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/sandbox.py`, `src/harness/adapters/claude_code.py`,
`src/harness/config.py`

## Problem
Concept §12 requires two guarantees. Neither fully holds for the implementer:

1. **File confinement is advisory.** `ClaudeCodeAdapter.run()` calls
   `sandbox.confine(workdir)` — which only validates the *workdir path
   value* — then spawns `claude` **on the host** with `Bash` in
   `--allowedTools` and a non-interactive permission mode. The agent can read,
   write, and execute anywhere the user can; nothing restricts it to the
   project root. Concept §12's own mechanism ("tool allow/deny rules") is not
   applied beyond the coarse tool list — no deny rules, no path scoping, no
   `--add-dir`-style restriction.
2. **Untrusted code executes on the host.** The review gate runs
   tests/lint/types inside Docker, but during implementation the agent itself
   runs the generated tests via its host `Bash` tool — the exact untrusted
   execution the container exists to isolate.
3. **No timeouts anywhere.** `Sandbox.run()` and the `claude -p` subprocess
   have no timeout; a hung container command or wedged agent blocks an
   unattended run forever, defeating the autonomous-operation goal (§16).
4. `SandboxConfig` exposes no `ephemeral` field even though `Sandbox` supports
   it (T-120: "the ephemeral-per-run option is available") — it is not
   selectable from config.

## Goal
The implementer's blast radius is the project root and the container; nothing
in the pipeline can hang forever.

## Creates / changes
- `claude_code.py` / `sandbox.py` — confine the real agent by the strongest
  mechanism the installed CLI supports, in order of preference: run `claude`
  itself inside the sandbox container (project bind-mounted, network per
  config); otherwise pass explicit permission deny rules / settings that
  restrict file tools to the project root and deny host-endangering Bash
  patterns. Document the chosen mechanism and its residual risk inline.
- Timeouts: `Sandbox.run(command, timeout_s=...)` and the adapter's process
  runner gain configurable timeouts (config: `sandbox.command_timeout_s`,
  `implementation.agent_timeout_s`; generous defaults). Timeout →
  `SandboxError`/`AdapterError` naming the command, so the retry/escalation
  path (T-210) handles it like any failure.
- `config.py` — add `sandbox.ephemeral: bool = true`, the two timeout fields;
  wire `ephemeral` through `cli.build_orchestrator`.

## Acceptance criteria
- A scripted agent attempt to write outside the project root fails (unit:
  deny-rule/command construction asserted; smoke: gated real attempt rejected).
- A sandbox command exceeding its timeout raises `SandboxError` (unit-tested
  with a sleeping fake/process).
- A hung `claude` process raises `AdapterError` after
  `agent_timeout_s` and the ticket enters the normal retry path.
- `sandbox.ephemeral: false` in config produces a `docker run` without
  `--rm`.

## Out of scope
- Per-domain network allowlisting (unchanged concept §20 open item).
- The devcontainer image definition itself.

## Connections
- **Depends on:** T-120, T-140.
- **Blocks:** trustworthy unattended real runs.
- **Relates to:** T-030, T-210, T-340.

## Testing
**Test-after / contract + smoke** (thin glue over Docker/CLI), per guidelines
§4.2. Command construction and timeout behaviour unit-tested; real confinement
smoke-tested behind availability gates.
