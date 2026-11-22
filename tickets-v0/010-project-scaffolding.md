# T-010 — Project scaffolding & tooling

**Phase:** v0 — Walking skeleton
**Module(s):** `harness/pyproject.toml`, `src/harness/` package skeleton, tool
config, `tests/` layout, CI

## Goal
Stand up the repository skeleton and the toolchain so every later ticket starts
from a green baseline: install, lint, format, strict type-check, and test all
pass on an empty-but-importable package.

## Creates / changes
- `pyproject.toml` — uv-managed; runtime deps (`pydantic>=2`, `typer`, the
  Anthropic SDK); dev deps (`ruff`, `pyright` or `mypy`, `pytest`,
  `pytest-cov`); `[tool.ruff]`, type-checker strict config, `[tool.pytest.ini_options]`.
- `src/harness/__init__.py` and empty stub modules matching the layout in
  guidelines §2 (`cli.py`, `config.py`, `folder.py`, `orchestrator.py`,
  `journal.py`, `freeze.py`, `dag.py`, `budget.py`, `gates.py`, `prompts.py`,
  `sandbox.py`, `stages/`, `adapters/`, `prompt_templates/`).
- `tests/unit/`, `tests/contract/`, `tests/fakes/` with `__init__` / conftest.
- `uv.lock`.
- CI workflow running `ruff check`, `ruff format --check`, the strict type
  checker, and `pytest`.

## Acceptance criteria
- `uv sync` installs cleanly and `import harness` works.
- `ruff check` and `ruff format --check` pass on the skeleton.
- `pyright` / `mypy --strict` passes with zero errors.
- `pytest` runs and is green (a single trivial sanity test is acceptable).
- CI runs all four checks on push and is green.

## Out of scope
- Any business logic in the stub modules (later tickets fill them).
- Multi-provider config; container images (T-120 owns the devcontainer).
- Publishing/release tooling.

## Connections
- **Depends on:** none.
- **Blocks:** all other tickets.
- **Relates to:** T-020 (primitives land immediately after).

## Testing
Test-after for the scaffold itself (a sanity test proving the package imports and
the toolchain runs). The real value is the green baseline the checks provide.
