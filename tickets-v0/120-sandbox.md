# T-120 — Sandbox (file confinement + container code-execution)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/sandbox.py`

## Goal
Provide the two required isolation guarantees so the implementation agent can run
generated tests safely: confine all file access to the project root, and run
untrusted generated code inside a container (concept §12).

## Creates / changes
- `sandbox.py`:
  - **File confinement** — a `Sandbox` interface enforcing read/write only within
    the project root (working-directory restriction; supports the agent's tool
    allow/deny rules).
  - **Code-execution isolation** — run tests/build commands inside a container
    (Docker via stdlib `subprocess`), project folder bind-mounted, **network
    disabled by default** or restricted to an allowlist; ephemeral-container
    option for the strongest setting.
  - Level selectable from `config.sandbox` (`file_confinement`,
    `code_execution`, `network`, `container_image`).

## Acceptance criteria
- File operations outside the project root are rejected with `SandboxError`.
- Commands execute inside the container with the project mounted, returning exit
  code + stdout/stderr.
- Network is off by default (`network: []`); an allowlist (e.g. `["pypi.org"]`)
  is honoured for dependency installation.
- The ephemeral-per-run option is available.

## Out of scope
- What to run inside the sandbox (the review gate, T-200, decides).
- Agent orchestration (T-140, T-210).

## Connections
- **Depends on:** T-020, T-040.
- **Blocks:** T-130, T-140, T-200, T-210.
- **Relates to:** T-030 (sandbox config). The concrete devcontainer image and
  network allowlist are a concept §20 open item.

## Testing
**Test-after / contract + smoke.** Confinement logic is unit-tested; container
execution is smoke-tested behind a Docker-availability skip.
