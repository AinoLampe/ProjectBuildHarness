# T-700 — Guideline-declared check commands (`spec/checks.yaml`) and root-wide change detection

**Phase:** v1 — improvements (approved 2026-09-14)
**Module(s):** `src/harness/stages/guidelines.py`, `src/harness/stages/review.py`,
`src/harness/stages/implement.py`, `src/harness/freeze.py`, `src/harness/folder.py`,
`src/harness/contracts.py`, `src/harness/cli.py`,
`src/harness/prompt_templates/v1/guidelines.md`

## Motivation
Two hard-coded assumptions in the review gate stop the harness at the Python border
and hide part of the implementer's work from the reviewer:
1. `run_objective_checks` runs literally `pytest`, `ruff check .`, `ruff format
   --check .`, `pyright` (review.py). Concept §10.3 says the gate runs "the ticket's
   tests … along with any other automated quality checks **the guidelines define**" —
   the guidelines are generated per project and may prescribe `npm test`, `go test
   ./...` or `cargo clippy`; today they are ignored. With R1 (existing projects) this
   is the normal case, not an edge case, and the Stage 0 survey (T-610) already
   detects the commands.
2. `snapshot_tree(self.folder.src_dir)` watches only `src/`: tests the IA writes under
   `tests/` — or anything in a project with a different layout — never appear in the
   reviewer's changed-file list, the very list the RA uses to spot out-of-scope edits.

## Goal
The guidelines stage declares the project's check commands as a validated, frozen
artifact the gate executes; change detection covers the whole project root minus
harness and tool directories.

## Creates / changes
- `contracts.py` — `CheckCommands(test: list[str], lint: list[str] = [], format:
  list[str] = [], types: list[str] = [], test_scope_style:
  Literal["append_paths","none"] = "append_paths", e2e_test: list[str] | None =
  None)` — each a command argv; `append_paths` means the gate appends the ticket's
  declared test paths (or the epic e2e dir) to `test`.
- `stages/guidelines.py` — the `guidelines.md` template demands a fenced YAML
  `checks:` block (schema above) inside `guidelines.md`, seeded from the project
  state's `suggested_checks` (T-610); `extract_check_commands(guidelines_md) ->
  CheckCommands` (pure; `StageError` if the block is missing or invalid, after one
  bounded re-ask); written to `spec/checks.yaml` (declared output;
  `folder.spec_checks_yaml`).
- `freeze.py` — `checks.yaml` frozen with the spec (manifest hash; old manifests load
  with `None`); `read_frozen` exposes `checks`.
- `stages/review.py` — `run_objective_checks(sandbox, test_paths, checks:
  CheckCommands | None = None)`: `None` → the current Python defaults (unchanged
  behaviour for every existing test); otherwise run `test` (+ paths per
  `test_scope_style`), `lint`, `format`, `types` in that order, skipping empty lists
  (`ObjectiveResult` fields for skipped checks are `True` with "(not declared)" in
  the output). `run_epic_gate_checks` (T-670) uses `e2e_test` when declared, else
  `test` + the e2e dir.
- `stages/implement.py` — reads `frozen.checks` and passes it through;
  `snapshot_tree(root, *, exclude: frozenset[str])` walks `folder.root` excluding
  `spec`, `journal`, `.git`, `.venv`, `venv`, `node_modules`, `__pycache__`,
  `.ruff_cache`, `.pytest_cache`, `.mypy_cache`, `dist`, `build` and
  `harness.config.yaml`; the fallback for "nothing changed" becomes `[]`, rendered as
  "(no files changed)" in the review prompt instead of `[src/]`.
- `cli.py` — `status` shows the declared commands on one line.

## Acceptance criteria
- Guidelines fixture with a `checks:` block → `spec/checks.yaml` written, frozen, and
  the gate's recording sandbox shows exactly the declared argv (with appended paths)
  in the declared order; a project whose guidelines declare only `test` runs only that.
- No `checks.yaml` (pre-T-700 project or old freeze) → the Python defaults run,
  byte-identical to today's commands (existing gate tests unchanged).
- Missing or invalid `checks:` block → one re-ask, then `StageError`.
- Fake IA writes `tests/test_x.py` and `src/x.py`: both appear in the reviewer's
  changed-file list; a write under `journal/` or `spec/` does not; a no-change round
  renders "(no files changed)".
- T-670's epic gate uses `e2e_test` when declared.

## Out of scope
- Installing toolchains into the container image (concept §20 container item).
- Per-language e2e runners beyond an argv (T-670 stays path-based).
- Git-based diffing (still not assumed).

## Connections
- **Depends on:** T-600, T-610, T-670, T-070, T-180, T-200, T-500, T-520.
- **Blocks:** none.
- **Relates to:** T-660, T-740.

## Testing
**Test-first** for `extract_check_commands`, command construction/order/skips,
snapshot exclusions and the changed set; `RecordingSandbox` for argv assertions; freeze
round-trip with and without `checks.yaml`.
