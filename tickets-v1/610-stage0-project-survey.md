# T-610 — Stage 0 project survey: `spec/project-state.md` so the spec stages see the existing project

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** new `src/harness/stages/survey.py`, `src/harness/contracts.py`,
`src/harness/folder.py`, `src/harness/config.py`, `src/harness/orchestrator.py`,
`src/harness/adapters/coding.py`, `src/harness/adapters/claude_code.py`,
`src/harness/freeze.py`, `src/harness/cli.py`, `src/harness/prompt_templates/v1/`
(`survey_summarise.md` new; `brainstorm.md`, `concept_write.md`,
`concept_self_review.md`, `guidelines.md`, `tickets.md` gain `{{project_state}}`)

## Motivation
R1 says the project folder may already contain a project (concept v1.1 §1, §6.0).
Today every spec stage is blind to it: `ConceptStage.inputs` is `requirements.md` +
`instructions.md`; `GuidelinesStage.inputs` is the concept; `TicketsStage` reads the
frozen spec — all enforced by `DeclaredIOGuard`. Only the implementer — a `claude -p`
process in the project root — ever sees existing code, by which time the concept,
guidelines and tickets were written as if the folder were empty: a different stack,
conflicting conventions, tickets that re-create what exists. The increment model
(T-620) makes this the *normal* case: every second increment runs over a folder the
harness itself filled.

## Goal
A Stage 0 that turns the project folder into a declared, frozen input artifact —
`spec/project-state.md` (+ `.json`) — read by the concept, guidelines and tickets
stages; trivial and free (no model call) for a greenfield folder.

## Creates / changes
- `contracts.py` — `ProjectSurvey` (pydantic): `mode: Literal["greenfield",
  "existing"]`; `inventory: Inventory` (top-level tree with per-directory file counts,
  languages by extension share, manifests found — `pyproject.toml`, `package.json`,
  `Cargo.toml`, `go.mod`, … — test directories, total files and lines, prior
  increments found under `spec/.history/`); `summary: SurveySummary` (model-written
  for existing projects, empty strings for greenfield: architecture, main components,
  conventions observed, entry points, test/build commands detected, risks and
  constraints for new work); `suggested_checks: list[str]` (detected commands —
  consumed by T-700; informational until then).
- `stages/survey.py` — `SurveyStage` implementing the `Stage` protocol. Pure,
  test-first logic: `is_greenfield(root) -> bool` (**greenfield = no files besides
  harness-owned ones**: `requirements.md`, `instructions.md`, `harness.config.yaml`,
  anything under `spec/` and `journal/`); `build_inventory(root, *, exclude) ->
  Inventory` (excludes `spec/`, `journal/`, `.git/`, `.venv/`, `venv/`,
  `node_modules/`, `__pycache__/`, `.ruff_cache/`, `.pytest_cache/`; deterministic
  ordering); `render_project_state_md(survey) -> str`. `run()`: greenfield → write the
  trivial survey, **no adapter call**; existing → inventory plus **one** read-only
  agent call rendered from `survey_summarise.md` (`{{inventory}}`, `{{requirements}}`),
  parsed with `parse_structured(..., SurveySummary)` — agent calls get no re-ask
  process (`000-overview.md` §6), so an invalid summary is written as an empty summary
  with a `DecisionRecord` noting it; write both files (markdown rendered from the
  structure). Declared inputs: `requirements.md` plus "the project tree" via the
  inventory walker (concept v1.1 §5's one exception, documented in the module
  docstring); declared outputs: the two files.
- `adapters/coding.py` — `InspectorAdapter` Protocol: `inspect(prompt: str) ->
  AgentResult` (read-only, fresh process).
- `adapters/claude_code.py` — `inspect()`: a fresh `claude -p` with `_REVIEW_TOOLS`,
  `--model <review model>`, cwd `project_root`, parsed from the same envelope as
  `run()` into `AgentResult(success, summary=<result text>, usage, cost_usd)`.
  `review()` is untouched here (T-650 makes it delegate to `inspect()`).
- `folder.py` — `spec_project_state_md`, `spec_project_state_json`.
- `config.py` — `ProjectConfig.mode: Literal["auto","greenfield","existing"] = "auto"`
  (`auto` → `is_greenfield`; an explicit value overrides detection and records a
  `DecisionRecord` when it contradicts it); `GatesConfig.survey: GatePolicy =
  "interactive"`; `ModelsConfig.survey: ModelRoute | None = None` (defaults to the
  `review` route; validated as an agent route when set).
- `orchestrator.py` — `run()` starts with `_ensure_stage_gated("survey",
  spec_project_state_md, policy, self._generate_survey)`; the gate is **skipped** and
  recorded as `auto_approve` when the survey is greenfield. The survey's agent call is
  wrapped like `_RecordingReviewerAdapter`: run-logged under stage `"survey"`,
  template `survey_summarise`, cost routed through `BudgetGuard.record_direct_cost`.
- `stages/concept.py`, `stages/guidelines.py`, `stages/tickets.py` — add the survey
  file to `inputs`; render `{{project_state}}` in `brainstorm`, `concept_write`,
  `concept_self_review`, `guidelines`, `tickets` (the frozen copy for `tickets`) and
  include it in each `generate()` call's `files`.
- `freeze.py` — `freeze_spec` snapshots `project-state.md` next to concept/guidelines
  (manifest gains `project_state_hash`; `FrozenSpec` gains `project_state_text`);
  `read_frozen` verifies it; manifests without the field still load (`None`, `""`).
- `cli.py` — `harness survey --project <dir>` runs Stage 0 standalone (moves the
  previous `project-state.*` aside into `spec/.invalidated/` first, T-330 style) and
  prints the markdown; `status` prints the survey mode.
- Templates — `survey_summarise.md` (new; one JSON object matching `SurveySummary`);
  the five spec-stage templates gain a "Current project state (Stage 0 survey)" block:
  for an existing project build *on* it — reuse its stack and conventions unless the
  requirements say otherwise; for greenfield it is a one-line note.
  `test_prompt_template_consistency.py` extended.

## Acceptance criteria
- Greenfield folder (only harness-owned files): `SurveyStage.run()` writes both files
  with `mode: greenfield`, makes **no** adapter call, and the orchestrator applies no
  interactive gate for stage `survey` (spy `gate_io` never called for it).
- Existing folder (fixture with `src/`, `tests/`, `pyproject.toml`): the inventory
  lists directories, languages, manifests and test dirs deterministically (same input
  → byte-identical `project-state.json`); exactly one `inspect()` call; the rendered
  markdown contains the model's summary; the run.log entry has stage `survey` and the
  reported cost lands in the budget ledger.
- `ConceptStage`, `GuidelinesStage`, `TicketsStage` each raise `FolderError` when
  `project-state.md` is missing (declared input) and each passes its content in the
  adapter's `files` (fake-adapter assertion).
- `freeze_spec` snapshots `project-state.md`; a later hand-edit of it re-freezes and
  invalidates downstream exactly like a concept edit (T-330 path).
- `project.mode: existing` on a greenfield folder forces the model call and records a
  decision; `project.mode: greenfield` on a non-empty folder skips it and records one.
- `harness survey` re-runs Stage 0, moving the previous artifacts aside, never
  deleting.
- `inspect()` contract test: read-only tool set, `--model` from the review route, no
  `--resume`/`--continue`, envelope parsed; gated smoke test when `claude` is on PATH.

## Out of scope
- Consuming `suggested_checks` (T-700).
- Increment archiving and the re-survey trigger on changed requirements (T-620).
- The draft-concept input (T-630).
- Per-language parsers (extension and manifest detection only).

## Connections
- **Depends on:** T-600, T-040, T-070, T-140, T-160, T-320, T-330, T-500, T-510.
- **Blocks:** T-620, T-630, T-640, T-650, T-680, T-700.
- **Relates to:** T-560, T-740.

## Testing
**Test-first** for `is_greenfield`, `build_inventory` (determinism, exclusions,
manifests, languages), `render_project_state_md`, the gate-skip rule, freeze inclusion,
the three stages' declared input; **test-after / contract** for
`ClaudeCodeAdapter.inspect()` with the injected process runner, plus a gated smoke
test. Fakes: a `FakeInspector` (or `FakeCodingAgent.inspect` script) so no real process
runs in the pipeline tests.
