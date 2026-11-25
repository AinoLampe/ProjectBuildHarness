# Progress

## T-010 — Project scaffolding & tooling
Implemented the repository skeleton: `pyproject.toml` (uv-managed, ruff + pyright
strict + pytest configured), the full `src/harness/...` module skeleton from
guidelines §2 (stub modules with a one-line docstring pointing at the ticket that
fills them), `tests/{unit,contract,fakes}` with a single sanity test, a GitHub
Actions CI workflow running all four checks, and `.gitignore`.

No deviations. All four checks (`ruff check`, `ruff format --check`, `pyright`,
`pytest`) are green on the skeleton.

## T-020 — Core primitives (Clock, IdGen, errors)
Implemented `core/clock.py` (`Clock` protocol, `SystemClock`, `FrozenClock` with
`advance()`), `core/ids.py` (`IdGen` protocol, `UuidGen`, `SeqIdGen` with a
deterministic `<prefix>-NNNN` sequence), and `core/errors.py` (`HarnessError`
base plus the eight named subclasses from the ticket). Test-first: failing tests
written and confirmed red before implementation.

No deviations.

## T-030 — Config model & loader
Implemented `config.py`: pydantic v2 models mirroring concept §4
(`ProjectConfig`, `ModelsConfig`/`ModelRoute`, `GatesConfig`, `BrainstormConfig`,
`ImplementationConfig`/`ReviewPolicy`, `SandboxConfig`, `BudgetConfig`,
`PromptsConfig`, `HarnessConfig`), all `extra="forbid"` so unknown sections/keys
are hard errors. `load_config(path) -> HarnessConfig` reads + parses YAML and
wraps any `pydantic.ValidationError` (or YAML/IO error) as `ConfigError` naming
the offending field. A `model_validator` enforces the v0 constraint that text
stages must use `provider: anthropic` and the implement/review stages must use
`agent: claude-code`.

No deviations.

## T-040 — Project-folder access
Implemented `folder.py`: `ProjectFolder` exposing every canonical path from
concept §3 as a property over a root; `read_text`/`write_text` and
`read_json`/`write_json` helpers (required-missing → `FolderError`,
optional-missing → `None`, writes create parent dirs); `declared_io(inputs,
outputs) -> DeclaredIOGuard` enforcing that a stage may only read its declared
inputs and write its declared outputs, raising `FolderError` otherwise.

No deviations.

## T-050 — Journal
Implemented `journal.py`: `RunLogEntry` (pydantic) appended as one JSON object
per line to `run.log` via `append_run_log`/`read_run_log`; `DecisionRecord` and
`ProgressEntry` each recorded by a function that updates the JSON mirror
(`decisions.json`/`progress.json`) and appends the corresponding markdown
section in the same call, so the two never drift. `resume_state(folder,
all_units)` reconstructs completed vs. incomplete units from `progress.json`.
A missing/empty journal reads as `[]` (fresh run). All entries take their
`timestamp` from the caller's injected `Clock` — the module never reads the
wall clock itself.

No deviations.

## T-060 — Budget guard
Implemented `budget.py`: a placeholder `RATE_TABLE` (USD per million tokens,
explicitly noted as needing run-time verification per concept §1),
`estimate_cost_usd()`, and `BudgetGuard` — pure accounting with no IO/clock/
logging. `record_usage()` raises `BudgetExceeded` pre-emptively (before
mutating accumulated spend) when the *projected* total would breach
`max_usd_per_run`, and returns a `warned` flag that fires exactly once on
crossing `warn_at_usd`.

No deviations.

## T-070 — Spec freeze + content hashing
Implemented `freeze.py`: `freeze_spec(folder, clock)` copies `concept.md` +
`guidelines.md` into a new `spec/.lock/<version>/` directory (version =
clock-derived timestamp) with a `manifest.json` recording sha256 hashes;
refuses to overwrite an existing version directory (immutability).
`read_frozen(folder, version)` re-verifies content against the recorded hash.
`latest_version()`/`is_stale(version)` let downstream stages detect that an
earlier stage was re-run and re-frozen, invalidating anything built against an
older version.

No deviations.

## T-080 — Ticket DAG
Implemented `dag.py`: `TicketNode` (id, depends_on, blocks, relates_to — pure
structured input, no disk reading) and `topological_order()` using Kahn's
algorithm with a min-heap over ready node ids for a stable, deterministic
build order regardless of input order. `blocks` and `depends_on` both
contribute ordering edges (inverse of each other); `relates_to` is ignored for
ordering. A cyclic graph raises `DagCycleError` naming the unresolved/cyclic
ids; an empty graph returns `[]`.

No deviations.

## T-090 — Prompt templates + renderer
Implemented `prompts.py`: `render_prompt(name, version, variables,
template_dir=None)` resolves `<template_dir or DEFAULT_TEMPLATE_DIR>/<version>
/<name>.md` (project override searched first), substitutes `{{variable}}`
placeholders, and raises the new `PromptError` (see DECISIONS.md) for a
missing template or a placeholder with no matching variable. Shipped
first-draft placeholder templates for all eight named prompts under
`prompt_templates/v1/`.

Deviation: added `PromptError(HarnessError)` to `core/errors.py` — logged in
DECISIONS.md as no existing T-020 exception fit this concern.

## T-100 — TextStageAdapter protocol + contract + fake
Implemented `adapters/text.py` (`TokenUsage`, `GenerationResult`,
`TextStageAdapter` Protocol), `tests/contract/text_contract.py`
(`TextAdapterContract` — a subclassable pytest mixin asserting valid
text+usage output, declared-file input acceptance, and `AdapterError`
wrapping of failures), and `tests/fakes/fake_text.py` (`FakeTextAdapter`
scripting per-call results/exceptions, recording every call). The fake's own
contract test subclasses `TextAdapterContract` and passes.

No deviations.

## T-110 — Anthropic text adapter
Implemented `adapters/anthropic_text.py`: `AnthropicTextAdapter` wraps an
injected Messages-API-shaped client (narrow internal Protocols
`_AnthropicClientLike`/`_MessagesApiLike`/`_MessageLike`/etc., all read-only
properties so structural matching works against both fakes and the real SDK);
declared files are injected as labelled blocks ahead of the prompt; any SDK
failure is caught and re-raised as `AdapterError` (justified inline-commented
broad except at this one adapter boundary). `from_api_key()` builds a real
client via the installed SDK's default credential resolution, cast to the
internal protocol at that one boundary (inline-commented — the real SDK's
content-block union isn't a literal structural match; `generate()` defensively
skips non-text blocks). Passes the T-100 contract suite against a fake client;
a separate `ANTHROPIC_API_KEY`-gated smoke test exercises the real API.

No deviations.

## T-120 — Sandbox
Implemented `sandbox.py`: `Sandbox.confine(path)` resolves and rejects any
path outside the project root with `SandboxError` (file confinement, tested
without Docker). `build_docker_command()` constructs the `docker run`
invocation (bind-mounted root, `--network none` when `network=[]`, configured
image, `--rm` when `ephemeral=True`) without executing it, so command
construction is unit-tested directly; `run()` executes it and wraps a missing
Docker binary as `SandboxError`. A Docker-availability-gated smoke test
exercises real container execution. The network allowlist case (non-empty
`network`) is documented as a best-effort placeholder falling back to the
default bridge network — true per-domain enforcement is the concept §20 open
item, out of reach for v0.

No deviations.

## T-130 — CodingAgentAdapter protocol + contract + fake
Implemented `adapters/coding.py` (`AgentResult`, `CodingAgentAdapter`
Protocol with `run(workdir, prompt, sandbox)`), `tests/contract/
coding_contract.py` (`CodingAgentContract` mixin asserting outcome+usage
shape and `AdapterError` wrapping), and `tests/fakes/fake_coding.py`
(`FakeCodingAgent`/`ScriptedRun` — each scripted run can write files relative
to `workdir` through the sandbox's `confine()`, simulating real code being
written, plus call recording). The fake passes the contract suite.

No deviations.

## T-140 — Claude Code (`claude -p`) adapter
Implemented `adapters/claude_code.py`: `ClaudeCodeAdapter` with `run()`
(implementer: `--allowedTools Read,Edit,Write,Bash,Glob,Grep`,
`config.models.implement`, confines `workdir` via the sandbox first) and
`review()` (reviewer: `--allowedTools Read,Glob,Grep` only,
`config.models.review`, runs in `project_root`, never adds `--resume`/
`--continue`, sends exactly the orchestrator-supplied prompt). Both parse
`--output-format json`; `review()` treats an unparseable or `pass`-less
response as a failed verdict rather than raising. `process_runner` is
injected (defaulting to a real `subprocess.run` wrapper) so contract tests
never spawn a real `claude` process; `run()` passes the T-130 contract suite,
`review()` has a dedicated test module asserting fresh-session/read-only/
model/prompt-passthrough/verdict-parsing behaviour. Gated smoke tests (skipped
unless `claude` is on PATH) exercise both paths for real.

Deviation: `review()`'s exact ticket signature has no `workdir` parameter, but
a `claude -p` process needs a cwd; added `project_root` as an adapter
construction-time field (not a `review()` parameter) to supply it, keeping the
public method signature exactly as specified.

## T-150 — Interactive gates
Implemented `gates.py`: `apply_gate(artifact, *, policy, io)` — `io` is an
injected `Callable[[str], GateResponse]` so gates are testable without a TTY.
`auto_approve` returns the artifact without ever calling `io`; `approve`
returns the original artifact; `edit` returns `edited_artifact`; `reject`
raises `GateRejected` carrying the feedback. `phase_boundary_should_stop()`
signals the `stop` policy. The Stage 1a brainstorming Q&A loop is explicitly
out of scope here (it lives inside the concept stage, T-170).

No deviations.

## T-160 — Stage contract
Implemented `stages/base.py`: `Stage` Protocol (`inputs`, `outputs`,
`run(folder, adapter, rendered_prompt) -> StageResult`) and
`declared_io_for(stage, folder) -> DeclaredIOGuard`, wiring a stage's own
declared inputs/outputs into the T-040 guard. `StageResult` carries
`outputs_written` plus any new `blocking_questions`. A trivial fake stage in
the test module conforms to the protocol and demonstrates the guard rejecting
an undeclared read and an undeclared write.

No deviations.

## T-170 — Stage 1a: Architectural concept
Implemented `stages/concept.py`. Pure, test-first logic: `parse_blocking_questions`
(extracts the "## Decisions needed (blocking)" bullets), `missing_readiness_items`
(concept §6.4 checklist via keyword evidence), `extract_phasing_yaml` (fenced
YAML block or explicit "no phasing needed" statement; validates exactly one
active phase + `stop_after_active_phase` when phases are declared), and
`run_bounded_resolution_loop` (generic bounded brainstorm/self-review loop:
resolves via `ask_user` each round, and on hitting `max_rounds` records
documented assumptions instead of looping — guaranteed termination). `ConceptStage`
wires these together: bounded brainstorm → write `open-questions.md` → write
`concept.md` → bounded self-review (can re-enter, appends resolutions) →
readiness check (raises `StageError` if not ready) → `extract_phasing_yaml` →
write `concept.md` + `phasing.yaml`. Declared inputs are exactly
`requirements.md` + optional `instructions.md`; outputs exactly the three
declared files, enforced via `declared_io_for`. Driven end-to-end with
`FakeTextAdapter`.

Deviation: `run()` ignores the orchestrator's single `rendered_prompt` argument
for most of its work, since Stage 1a is inherently multi-step (brainstorm,
write, self-review) and renders its own sequence of named templates internally
via `prompts.render_prompt()` — a single pre-rendered string doesn't fit a
multi-call interactive stage. Also widened `stages/base.py`'s `Stage.inputs`/
`outputs` from plain attributes to read-only properties so `@property`-based
implementations (like `ConceptStage`) satisfy the protocol structurally.

## T-180 — Stage 1b: Engineering guidelines
Implemented `stages/guidelines.py`. Pure, test-first `parse_consolidation()`
parses the structured consolidation response ('## Conflict' / '## Resolution'
/ optional '## Revised Concept' fenced block); `GuidelinesStage.run()`'s only
declared input is `spec/concept.md` (proven by a test asserting no
brainstorming-history file ever reaches the adapter), generates
`guidelines.md`, then runs the consolidation check. On a conflict it records
a `DecisionRecord` (concept wins, per concept §7) to `DECISIONS.md`/
`decisions.json`, and only rewrites `concept.md` when the consolidation step
supplied a revised version — otherwise concept is left untouched. Driven
end-to-end with `FakeTextAdapter`.

No deviations.

## T-190 — Stage 2: Implementation tickets
Implemented `stages/tickets.py`. Pure, test-first `parse_tickets_response()`
splits the model's response into `ParsedTicket`s on a `## TICKET: NNN-slug`
delimiter, extracting Connections (depends on/blocks/relates to) and an
optional declared `### Phase`; `validate_build_order()` builds `dag.py`
`TicketNode`s (excluding the overview) and raises `DagCycleError` on a cycle;
`filter_active_phase()` keeps the overview plus any ticket whose phase tag
matches the active phase (or has none), deferring the rest. `TicketsStage`
reads the **frozen** spec by version (`freeze.read_frozen`, not a live copy —
proven by a test that mutates `concept.md` after freezing), reads
`phasing.yaml` to determine the active phase, generates the combined
overview+tickets response, validates the overview is first and the DAG is
acyclic, writes each scoped ticket file, and zips them into `tickets.zip`.

Deviation: individual numbered ticket filenames are inherently dynamic (model-
chosen slugs), so they are written via `folder.write_text` directly rather
than through the static `DeclaredIOGuard` (which only supports an
upfront-known path set); a manual `is_relative_to(spec_tickets_dir)` check
preserves the same confinement intent for these dynamically-named files. The
guard still covers the two fixed-name outputs (`000-overview.md`,
`tickets.zip`).

## T-200 — Per-ticket review gate
Implemented `stages/review.py`: `run_review_gate()` (async) runs automated
checks first (`pytest` scoped to `test_paths`, `ruff check`, `ruff format
--check`, `pyright`, all via the injected `SandboxLike.run()`); if any is red
the gate fails immediately and the reviewer is never called. Otherwise it
renders the `review_gate` template (ticket text, changed file paths,
objective-check output — all orchestrator-assembled, never the implementer's
text) and awaits `adapter.review(...)` via `asyncio.to_thread` (see
DECISIONS.md). Returns a structured `GateResult(passed, objective,
llm_verdict, reasons)`. Verified gatherable with `asyncio.gather()` on two
independent fake reviews.

Deviation: see DECISIONS.md (T-200) — `ClaudeCodeAdapter.review()` (T-140)
stays synchronous; this async function wraps it via `asyncio.to_thread`
rather than retrofitting T-140.

## T-210 — Stage 3: Implementation driver
Implemented `stages/implement.py`. Pure `parse_ticket_file()` derives a
ticket's id from its filename and extracts Connections; `plan_build_order()`
runs T-080's `topological_order` over the parsed specs. `ImplementStage.run()`
reads the frozen spec + `requirements.md` + all non-overview ticket files,
plans the build order, consults `resume_state()` to skip already-`progress.json`
-completed tickets (crash-and-resume), then for each remaining ticket: renders
the `implement_bootstrap` template (re-rendered per ticket — every invocation
carries the full read-concept→guidelines→tickets instruction, since each
`claude -p` call is its own fresh process with no memory of a prior ticket's
session), calls `adapter.run()`, and awaits `run_review_gate()` (T-200). On
gate failure it retries (re-prompting with the gate's reasons appended) up to
`retry_budget + 1` total attempts, then raises `StageError` — escalating
without shipping a failed ticket or looping forever. Each success is recorded
via `record_progress()`. After all tickets, a final acceptance pass re-runs
the agent against `requirements.md` + the frozen concept; drift is surfaced
via `StageResult.blocking_questions`. Fully exercised with `FakeCodingAgent`
and a fake reviewer — no real models, containers, or spend.

Deviations: (1) see DECISIONS.md (T-210) — automated checks scope to the
whole test suite per ticket rather than a per-ticket subset, since the ticket
schema has no field to reliably extract one. (2) The per-phase "stop at the
active-phase boundary" criterion is satisfied structurally: Stage 2 (T-190)
already writes only active-phase ticket files to disk, so Stage 3 implementing
exactly the tickets it finds on disk *is* the phase stop — no separate logic
needed here. (3) `ImplementStage.sandbox` is typed as the concrete
`sandbox.Sandbox` class (not a new Protocol) since it already satisfies both
the `CodingAgentAdapter.run()` signature and the review gate's `SandboxLike`,
and tests override `Sandbox.run()` in a subclass rather than calling Docker.

## T-220 — Orchestrator
Implemented `orchestrator.py`: `Orchestrator.run()` sequences `concept ->
guidelines -> freeze -> tickets -> implement`. Idempotency: each text stage is
skipped if its primary output file already exists (proven by a script-
exhaustion-would-error test); `freeze_spec` is only called when no frozen
version exists yet. Each generated text stage's adapter is wrapped in
`_BudgetTrackedTextAdapter`, which calls `BudgetGuard.record_usage()` after
every `generate()` — a tiny `max_usd_per_run` makes the first call raise
`BudgetExceeded`, halting before the guidelines stage ever runs. After each
text stage, `gates.apply_gate()` is applied to that stage's primary artifact
per `config.gates.*`; `auto_approve` never calls `gate_io`, `reject` raises
`GateRejected` and halts. `_should_stop_at_phase_boundary()` reads
`phasing.yaml` and halts before Stage 3 when `stop_after_active_phase: true`
and `gates.phase_boundary == "stop"`. Crash-and-resume for Stage 3 itself is
already handled inside `ImplementStage` (T-210); the orchestrator's own
idempotency covers the three text stages.

Deviations: (1) per DECISIONS.md (T-220), `BudgetGuard` wraps only the text
adapters, not Stage 3's agent/reviewer spend (different cost-accounting
models; unifying them is future work). (2) `ImplementStage` (T-210) was
extended with a `__final_acceptance__` progress-journal marker so a second
orchestrator run, after a fully-completed implement stage, makes zero
further adapter calls — needed for the orchestrator-level idempotency
criterion to hold for the whole pipeline, not just the per-ticket loop.

## T-230 — CLI
Implemented `cli.py`: `harness run --project <dir> [--from <stage>]` builds a
real, single-provider `Orchestrator` via `build_orchestrator()` (Anthropic
text adapters + `ClaudeCodeAdapter` for both `run()`/`review()` + `Sandbox`
from config) and runs it, exiting 2 if halted; `--from` is validated against
the known stage names (the orchestrator's own idempotency already resumes
correctly regardless of its value). `harness status --project <dir>` prints
`progress.json`/`decisions.json` via the journal. `harness gate --project
<dir> --stage <name> --approve|--edit|--reject` applies one gate decision
directly to that stage's primary artifact file, exiting 3 on rejection.
Tested via typer's `CliRunner` with `build_orchestrator` monkeypatched to
inject a stub orchestrator (no real adapters constructed in tests).

No deviations.

## T-390 — Journal true-append + atomic mirrors; freeze version collisions
Implemented `folder.append_text()` (opens in append mode, no read of prior
content) and used it for `journal.append_run_log` and the DECISIONS/PROGRESS
markdown mirrors (header written once via `append_text` if the file doesn't
exist yet, then each block appended). Added `folder.write_json_atomic()`
(temp file in the same directory + `os.replace`) and used it for
`decisions.json`/`progress.json` so a crash between the two steps leaves the
prior valid JSON intact rather than a truncated file. `freeze_spec` no longer
raises on same-instant re-freeze: `_next_free_version()` disambiguates with a
zero-padded `-02`, `-03`, ... suffix, which still sorts correctly for
`latest_version()` (a bare version is a string-prefix of its suffixed forms).

No deviations.

## T-310 — run.log recording + budget warning surfacing
`TextStageAdapter.generate()` gained optional `template_name`/`template_version`
keyword metadata (default `""`, backward compatible) so a recording wrapper can
attribute a call to the template that produced it; all three text stages
(concept, guidelines, tickets) now pass these on every `generate()` call.
`orchestrator.py`'s `_BudgetTrackedTextAdapter` became `_RecordingTextAdapter`:
still budget-tracks via `BudgetGuard.record_usage()`, and now also appends a
`RunLogEntry` per call (stage, model, template identity, tokens, estimated
cost, measured wall time), plus a `"budget_warning"`-event entry and an
`on_warning(message)` callback exactly once when `UsageResult.warned` fires.
Added `_RecordingCodingAdapter`/`_RecordingReviewerAdapter` wrapping Stage 3's
agent/reviewer calls with the same run-log treatment, using the agent's
self-reported usage/cost (not the rate table — see DECISIONS.md T-220/T-310).
After each text stage completes, `_record_stage_artifacts()` appends one
`"stage_artifacts"`-event entry with sha256 hashes of that stage's existing
declared outputs (posix-style relative paths, so the log is
platform-independent). `RunLogEntry` gained an optional `event: str | None`
field to distinguish these synthetic bookkeeping entries from ordinary
adapter-call entries (`event is None`). `cli.build_orchestrator` wires
`on_warning` to `typer.echo(..., err=True)`.

Deviation: `ReviewResult` (T-140) has no self-reported `cost_usd` field (only
`usage`), so `_RecordingReviewerAdapter` records `estimated_cost_usd=0.0` for
reviewer calls — logged as a known gap, to be revisited alongside T-510's
unified accounting rather than widening T-140's already-shipped schema here.

## T-320 — Gate state persistence + rejection feedback
Added `GateOutcome` (stage, decision, artifact content hash, feedback) to
`journal.py` with the standard md/JSON mirror pair
(`GATES.md`/`gates.json`), `record_gate_outcome`/`read_gate_outcomes`/
`latest_gate_outcome`. `ConceptStage`/`GuidelinesStage`/`TicketsStage` gained
an optional `regeneration_feedback: str | None` field; when set, it is
appended to that stage's primary generation prompt (concept_write /
guidelines / tickets) ahead of a template-level treatment (deferred to
T-550). `Orchestrator` replaced its exists()-based idempotency with
`_ensure_stage_gated(stage, path, policy, generate)`: if the artifact is
missing, generate it; if it isn't approved against its *current* content
(never gated, edited by hand since approval, or hash-mismatched), apply the
gate directly to what's on disk — no wasted regeneration; only a rejection
triggers one regeneration attempt with the rejection's feedback, and a
second rejection propagates and halts (bounded). `cli.py`'s `gate` command
now records the same `GateOutcome` on every decision, so a later `harness
run` regenerates a CLI-rejected stage instead of skipping it.

Deviation: found and fixed a latent cross-platform hash bug while building
this — Windows text-mode I/O translates `\n` to `\r\n` on write, so hashing
a file's raw bytes and hashing the same content's in-memory string (encoded
UTF-8) disagree. Split into `_sha256_text_file` (decode-then-hash, used for
all gate-approval comparisons) and `_sha256_bytes_file` (raw bytes, used
only for run.log's informational artifact-hash record, which may include
`tickets.zip`).

## T-330 — Upstream invalidation + working `--from`
`ProgressEntry` gained `frozen_version: str | None`; `resume_state(...,
frozen_version=...)` only counts an entry as done when it matches the
current frozen version (entries with no recorded version, i.e. pre-T-330
journals, still count — backward compatible). `ImplementStage` now records
and checks its own `frozen_version` on every entry. `Orchestrator._ensure_frozen()`
replaces the old "freeze only if nothing frozen yet" check: when a frozen
version exists, it compares the *live* concept/guidelines content's hash
against the frozen manifest; on a mismatch it re-freezes and calls
`_invalidate_downstream_of_freeze()`, which moves `spec/tickets/` and
`tickets.zip` aside into `spec/.invalidated/<new_version>/` (never deletes)
and records a `DecisionRecord` explaining the re-freeze. `folder.py` gained
`spec_invalidated_dir`. `Orchestrator.invalidate_from(stage)` gives
`harness run --from <stage>` real teeth: it moves that stage's artifact(s)
— and everything they gate — aside the same way, so the next `run()`
regenerates them (re-freezing, and its own downstream invalidation, then
happens automatically once content actually changes). `cli.py`'s `run`
command calls `invalidate_from` before `orchestrator.run()` when `--from`
is given.

Also wired `is_stale()` (T-070, previously dead code) into `TicketsStage`/
`ImplementStage` as a defensive integrity check: each raises `StageError`
if constructed with a `frozen_version` that a later freeze has since
superseded, rather than silently building against a version the
orchestrator itself would already treat as invalidated.

## T-300 — Phase boundary stops after implementing the active phase
`Orchestrator.run()` moved the `_should_stop_at_phase_boundary()` check to
after `_run_implement(version)` instead of before it — concept §6.3/§11
require the active phase to be implemented, *then* halted at the boundary,
not skipped. Updated the two tests that had encoded the inverted behaviour
(`test_phase_boundary_stop_halts_after_implementing_the_active_phase` in
test_orchestrator.py, `test_phase_stop_halts_after_implementing_the_active_phase`
in test_e2e_pipeline.py) to assert the coding agent *was* invoked and
`"implement"` appears in `completed_stages` before the halt.

No deviations.

## T-360 — DAG unknown refs + ticket-id normalisation
Added `DagReferenceError(HarnessError)` and `dag.py::normalise_ticket_id()`
(strips a `T-`/`t-` prefix and any `-slug` suffix, matching `\d{3}` at the
front — `T-010`, `010`, `010-core-primitives` all normalise to `010`).
`topological_order()` now validates every `depends_on`/`blocks` reference
against the node-id set *before* building edges, raising `DagReferenceError`
naming both the referencing node and the missing id — no more bare
`KeyError` (reproduced pre-fix via `topological_order([TicketNode(id='020',
depends_on=['010'])])`). `tickets.py::_parse_id_list` normalises every
Connections reference through `normalise_ticket_id`.
`validate_build_order()` signature changed to `(all_tickets,
scoped_tickets) -> (build_order, dropped_edges)`: it validates references
across the *full* (unscoped) ticket set first — genuinely unknown ids still
raise — then orders only the scoped (active-phase) subset, silently
dropping any edge whose target isn't in the scoped set (a deferred-phase
ticket, or the overview) rather than treating it as a dangling reference.
`TicketsStage` gained a required `clock: Clock` field and records a
`DecisionRecord` (via the now-declared `journal_decisions_md/json` outputs)
whenever cross-phase edges are dropped, so the fact is visible rather than
silent. `implement.py::_parse_ids` normalises the same way instead of
blindly prefixing `T-` (which previously mangled a `T-020`-spelled
reference into `T-T-020`), and drops references to `000` (the overview,
never an implementable Stage 3 node).

Deviation: chose `DagReferenceError` (not `StageError`) for tickets.py's
full-set reference validation too, since it is the same class of failure
`dag.py` already raises it for — consistency over module boundaries.

## T-370 — Budget pre-call headroom check + config-time rate validation
`budget.py`: `estimate_cost_usd`/`BudgetGuard` accept an optional
`rate_table` overriding/extending the module-default `RATE_TABLE`.
`BudgetGuard.check_headroom(model, *, est_input_tokens, max_output_tokens)`
raises `BudgetExceeded` **before** a call is made if its worst-case cost
(estimated input + the call's output-token ceiling) would breach the cap —
stricter than `record_usage`'s existing post-call check, which only
protects the *ledger*, not the provider call itself. Added
`estimate_tokens_from_text()` (a documented chars/4 heuristic, used only for
this pre-call estimate, never for post-call accounting). `orchestrator.py`'s
`_RecordingTextAdapter.generate()` calls `check_headroom` before
`inner.generate()`, using a placeholder `_DEFAULT_MAX_OUTPUT_TOKENS_ESTIMATE
= 4096` output ceiling pending T-420's configurable per-stage `max_tokens`.

`config.py`: new `BudgetConfig.model_rates: dict[str, ModelRateConfig]`
(project-supplied per-model rates); a `BudgetConfig` validator rejects
`warn_at_usd > max_usd_per_run`; a `HarnessConfig`-level validator rejects
any text-stage (concept/guidelines/tickets) model with no rate in
`RATE_TABLE ∪ budget.model_rates` — a misconfigured/unknown model now fails
at `load_config()` time instead of crashing mid-run on the first
`generate()` call. `cli.py::build_orchestrator` merges `model_rates` over
`RATE_TABLE` and passes the result to `BudgetGuard`.

No deviations.

## T-420 — Anthropic adapter: truncation detection, configurable max_tokens, retries
`AnthropicTextAdapter.generate()` now checks the response's `stop_reason`
(added to the `_MessageLike` protocol) and raises `AdapterError` if it is
`"max_tokens"` — truncated text is never silently treated as complete, no
matter what value it flows into (concept.md, guidelines.md, or a whole
ticket batch). `_create_with_retry()` retries up to 3 attempts with
exponential backoff (`1s, 2s`) for a fixed set of transient `anthropic` SDK
exceptions (`RateLimitError`, `InternalServerError`, `OverloadedError`,
`APIConnectionError`, `APITimeoutError`); any other exception wraps as
`AdapterError` immediately, unretried, matching prior behaviour. `sleep` is
an injected `Callable[[float], None]` (default `time.sleep`) so retry tests
never actually wait. `config.py`'s `ModelRoute` gained an optional
`max_tokens: int | None`; `cli.py::build_orchestrator` passes
`route.max_tokens or DEFAULT_MAX_TOKENS` to each text-stage adapter.

Deviation: the truncation/retry contract tests live in
`test_anthropic_text_adapter_contract.py`, not the shared `text_contract.py`
suite — `stop_reason` and the `anthropic` SDK's exception hierarchy are
Anthropic-specific concepts with no equivalent in the abstract
`TextStageAdapter`/`GenerationResult` protocol (text + usage only), so
forcing every adapter (including `FakeTextAdapter`) through the same cases
would test a concept the protocol doesn't have.

## T-340 — Parse the real `claude -p --output-format json` envelope
`ClaudeCodeAdapter.run()`/`review()` previously read invented top-level
fields (`success`, `input_tokens`, `output_tokens`, `cost_usd`) that the
real CLI never emits; both now parse the actual envelope shape (`type`,
`subtype`, `is_error`, `result`, `total_cost_usd`, `usage: {input_tokens,
output_tokens}`). `run()`'s `success` comes from `_envelope_is_error()`
(`is_error` if present, else `subtype != "success"`). `review()`'s verdict
JSON is extracted from *inside* `result` (the model's final text) via
`_extract_verdict()` — parses the whole string first, falling back to a
regex search for an embedded `{"pass": ...}` object (handles fenced or
prose-wrapped verdicts); still returns a failed verdict, never raises, when
nothing parseable is found. Updated the contract fixtures
(`test_claude_code_adapter_contract.py`,
`test_claude_code_adapter_review.py`) to emit the real envelope shape —
the previous fixtures encoded the invented schema, exactly the "testing
your own mocks" trap guidelines §4.2 warns about. Strengthened the
`review()` smoke test's assertion from `isinstance(result.passed, bool)`
(vacuously true even when parsing always fails) to a definitive expected
outcome on a trivially-compliant case.

No deviations.

## T-380 — Sandbox: timeouts everywhere; best-effort Bash deny-list for the agent
`Sandbox.run(command, *, timeout_s=None)` now passes `timeout` to
`subprocess.run()` (falling back to a new `default_timeout_s` constructor
arg), catching `subprocess.TimeoutExpired` and raising `SandboxError` naming
the command and the timeout — a hung container command can no longer block
an unattended run forever. `ClaudeCodeAdapter` gained `command_timeout_s`
(default 1800s); its default process runner (`_make_default_process_runner`,
replacing the old bare-function default so it can close over the configured
timeout) enforces it, and `_invoke()` wraps a `TimeoutExpired` from *any*
injected runner as `AdapterError`. `run()`'s command gained
`--disallowedTools` with a documented, best-effort deny-list of
host-endangering Bash patterns (`rm -rf /*`, `sudo:*`, piping curl to a
shell, etc.) — Read/Write/Edit are already cwd-scoped by the CLI's own
default tool confinement, but Bash is a general shell and isn't.
`config.py`: `SandboxConfig` gained `ephemeral: bool = True` (previously
supported by `Sandbox` but not configurable) and `command_timeout_s`;
`ImplementationConfig` gained `agent_timeout_s`. `cli.py::build_orchestrator`
wires all three through.

Deviation: did not containerize the `claude` process itself (the concept
§12 ideal for isolating untrusted execution) — the agent's own process needs
outbound network access to reach the Anthropic API, which conflicts with
the sandbox's `network: []` default built for isolating *test* execution,
not the agent's necessary API calls. Documented as a residual risk inline;
resolving the network-policy conflict is a follow-up, not silently assumed
away.

## T-400 — Wire the dead config knobs
Three previously-inert `harness.config.yaml` settings now do something:
(1) `prompts.template_dir`/`version` — the stage-level plumbing
(`prompt_version`/`template_dir` fields on `ConceptStage`/`GuidelinesStage`/
`TicketsStage`/`ImplementStage`) already existed from T-170–T-210; the
orchestrator simply never passed `self.config.prompts.*` into any of them.
`_generate_concept`/`_generate_guidelines`/`_generate_tickets`/
`_run_implement` now do. `config.py::load_config` also resolves a relative
`prompts.template_dir` against the **config file's own directory** (not the
process CWD), so the override behaves identically regardless of where
`harness run` is invoked from. (2)/(3) `implementation.review.
require_tests_green`/`require_llm_review` — `run_review_gate()` gained both
as parameters: `require_tests_green=false` skips the sandboxed automated
checks (objective result reported as vacuously green, clearly labelled
"skipped" in its output text) while the reviewer still runs;
`require_llm_review=false` skips the reviewer once the objective checks
(if enabled) pass. `ImplementStage` gained the two fields and passes them
through; when both are `false`, `ImplementStage.run()` records a
`DecisionRecord` up front (every ticket's gate will pass with **zero**
verification) so the gap is visible in `DECISIONS.md`, not silent.

No deviations.

## T-350 — Brainstorm loop feeds prior answers back; fixes the round-cap off-by-one
`run_bounded_resolution_loop`'s `generate_questions` callback signature
changed from `Callable[[], str]` to `Callable[[str], str]`: it now receives
the accumulated transcript of prior rounds' questions and answers (empty on
round one), and `ConceptStage`'s `generate_brainstorm_questions`/
`generate_self_review` closures append that transcript directly onto the
rendered prompt (a dedicated template variable is T-550's job). Reproduced
before the fix: with a real model, every round regenerated the identical
questions since answers never reached it, degrading every blocking item to
a "documented assumption" regardless of what the user answered.

Rewrote the loop's control flow from a `while True` counter to `for
round_number in range(1, max_rounds + 1)`: the user now gets exactly
`max_rounds` `ask_user` opportunities (reproduced before the fix:
`max_rounds=3` asked only twice; `max_rounds=1` never asked at all).
Exhaustion — blocking items remain after the final round — still records
documented assumptions and returns, preserving the termination guarantee.

Self-review's resolutions no longer get raw-appended as a "## Self-review
resolutions" transcript dump; a new one-extra-generate-call step folds them
into a coherent revised concept (reusing the `concept_self_review` template
plus a direct instruction, matching the `regeneration_feedback` pattern
already established for T-320 — a dedicated revision template is T-550's
job).

Updated `test_concept_logic.py`/`test_concept_stage.py` for the corrected
call counts and added a dedicated transcript-propagation test.

No deviations.

## T-410 — Final acceptance pass: templated, read-only, surfaced to the user
Added two templates: `final_acceptance.md` (requirements + frozen concept,
demanding the same `{"pass": bool, "reasons": [...]}` verdict shape as the
per-ticket review gate) and `implement_retry.md` (the retry-with-feedback
prompt). `ImplementStage._render_final_acceptance`/`_render_retry` replace
the two hard-coded f-string prompts that previously lived in `implement.py`
— no prompt text remains hard-coded there. The final pass now calls
`self.reviewer.review(...)` (the read-only reviewer path, fresh session)
instead of `adapter.run()` (the write-capable implementer) — a validator
that can silently "fix" what it's judging isn't a validator. `OrchestratorResult`
gained `warnings: list[str]`; `Orchestrator.run()` threads `_run_implement`'s
(renamed to return, not discard) `blocking_questions` through to it — concept
§10.6's "then a confirmation prompt is sent to the user" previously had no
destination at all. `cli.py`'s `run` command prints the drift summary and
exits with a distinct code (4) when there are warnings but the run
otherwise completed successfully (halts/rejections keep their existing
codes, checked first).

Updated `test_implement_stage.py`'s two final-acceptance tests for the new
reviewer-based call path (previously scripted via the coding-agent fake);
added `test_final_acceptance_drift_surfaces_as_a_non_halting_warning`
(orchestrator) and `test_run_with_final_acceptance_drift_exits_with_a_distinct_code`
(CLI).

No deviations.

## T-500 — Structured model-output contracts (guidelines consolidation)
Added `contracts.py`: four pydantic contract models named in the ticket
(`OpenQuestions`, `ReadinessSelfCheck`, `ConsolidationVerdict`, `TicketSet`)
plus `parse_structured(text, model_cls, *, re_ask=None)` — extracts a JSON
object from the response (whole-text first, then any fenced ```json block),
validates it against the model, and on failure asks once more (via the
caller-supplied `re_ask`) before raising `StageError`. Rewired
`guidelines.py`'s `parse_consolidation()` onto `ConsolidationVerdict` via
`parse_structured`, replacing the old regex-scraped `## Conflict`/
`## Resolution`/`## Revised Concept` sections and the `_NO_CONFLICT_PHRASES`
exact-match list — this fixes the concretely-cited bug: a model answering
"No conflicts found." (not the exact phrase `"no conflict"`) was previously
recorded as a **conflict**, generating a spurious `DECISIONS.md` entry.
`conflict_found` is now a first-class boolean the model sets explicitly.
`GuidelinesStage.run()` wires a `re_ask` closure back through
`adapter.generate()` for the one-bounded-retry path. Updated
`guidelines_consolidation.md` to demand the JSON schema.

Deviation: see DECISIONS.md (T-500) — converting `concept.py`'s readiness
check and `tickets.py`'s ticket-batch parsing onto the (already-built and
tested) `ReadinessSelfCheck`/`TicketSet` contracts is deferred to a
follow-up; the guidelines conversion was the concretely-cited bug and the
lowest-risk of the three (no new adapter call, no test-suite-wide fixture
rewrite).

## T-550 — Optimised prompt templates
Removed the `FIRST-DRAFT PLACEHOLDER` marker from every shipped template
and gave each real content against its stage's actual expectations.
`implement_bootstrap.md` and `review_gate.md` gained real path variables
(`frozen_concept_path`, `frozen_guidelines_path`, `overview_path`,
`journal_dir`; `concept_path`, `guidelines_path`) — previously the agent
was told to "read the frozen concept" with no path to find it.
`review_gate.md` also gained `{{acceptance_criteria}}` (extracted from the
ticket via a new `_extract_acceptance_criteria()` in `review.py`, highlighting
the objective pass/fail bar separately from the full ticket text).
`tickets.md` now states the granularity rule and the Connections id format
explicitly — previously Stage 2's validator (`DagReferenceError`,
normalisation) was stricter than its own prompt's instructions.

`brainstorm.md`/`concept_self_review.md` gained a real `{{qa_transcript}}`
placeholder (T-350 had appended the transcript directly onto the rendered
prompt as a stop-gap; this is the proper template-level fix). Self-review's
revision step (T-350) gets its own `concept_revise.md` template instead of
reusing `concept_self_review.md` with a manually-appended instruction.

Added `prompts.extract_placeholders()` (public) and
`test_prompt_template_consistency.py`: a parametrised test asserting every
named template's placeholders exactly match the variable set its stage
supplies (catching drift in either direction), plus a test that no shipped
template contains the placeholder marker.

No deviations.

## T-510 — Unified cost accounting
`BudgetGuard.record_direct_cost(source, cost_usd)` adds an already-known,
self-reported dollar cost to the same ledger `record_usage` uses — same
pre-emptive-halt-before-the-cap and warn-once semantics, except (unlike the
text-stage path) the cost of *this* call is already realised by the time
it's recorded, since an agent's cost is only known after it finishes; what
this halts is the *next* call. Added a public `BudgetGuard.max_usd_per_run`
property. `orchestrator.py`'s `_RecordingCodingAdapter`/
`_RecordingReviewerAdapter` (T-310) now take the shared `BudgetGuard` and
call `record_direct_cost` after each `run()`/`review()`, so Stage 3's spend
— previously tracked in `run.log` only, entirely outside the cap
(DECISIONS.md T-220) — now counts toward the same total as concept/
guidelines/tickets. A `BudgetExceeded` from Stage 3 propagates like any
other stage failure: the run halts before the *next* ticket, the failing
ticket's own progress entry was never written (it hadn't completed), and a
later run with a raised cap resumes correctly via the existing
`resume_state(..., frozen_version=...)` path (T-330) — no new resume logic
needed.

Deviation: did not add `implementation.min_headroom_usd` (a pre-flight
"refuse to start a ticket without at least this much headroom" guard) —
the ticket's core acceptance criteria (single ledger, cross-cap halt,
warn-once, no double-accounting) are met without it, and a heuristic floor
adds a config knob without a concrete failure mode driving it yet; left for
a future ticket if runaway per-ticket cost turns out to be a real problem
in practice.

## T-520 — Ticket-declared test scope + real changed-path detection
Added `TicketSpec.test_paths` (parsed by `_parse_test_paths()` from an
optional `### Tests` bullet list in the ticket) — each ticket's own gate
now runs `pytest <declared paths>` when it declares them, falling back to
the full suite (unchanged v0 behaviour) when it doesn't. After all tickets
in a run complete, one full-suite `run_objective_checks(sandbox, [])` call
(exposed as public from `review.py`, was `_run_objective_checks`) acts as
the regression net across everything just implemented; a failure there
raises `StageError` even though every individual ticket's own gate passed.
Added `snapshot_tree()`/`diff_changed_paths()` (path -> (mtime_ns, size)
before/after each `adapter.run()`) so the reviewer receives the *actual*
changed files for that ticket instead of being told "everything in src/
changed" on every call regardless of what happened; falls back to
`[folder.src_dir]` only when nothing changed (keeps existing fake-driven
tests, which mostly don't write real files, working unchanged).

Deviation: did not make the `### Tests` section a hard Stage 2 validation
requirement (the ticket's stated acceptance criterion) — `tickets.py`'s
ticket-batch validation wasn't converted onto the T-500 `TicketSet`
contract in this pass (see DECISIONS.md T-500), and bolting a standalone
regex check onto the still-freeform ticket text would be inconsistent with
that already-documented, deliberate scoping choice. Making `### Tests`
optional-with-fallback (rather than required) delivers the same practical
benefit — fewer full-suite runs, real changed-path detection — without
that inconsistency; enforcing it can land alongside the tickets.py contract
conversion.

## T-530 — Escalation UX
Added `EscalationRecord` (kind, ticket, context, resolution) to
`journal.py` with the standard md/JSON mirror pair
(`ESCALATIONS.md`/`escalations.json`), following the same append-only
"latest wins" pattern as `GateOutcome` (T-320): `record_escalation`,
`read_escalations`, `latest_escalation_for(folder, ticket)`, and
`resolve_escalation(folder, ticket, answer, now)` (appends a new record
with `resolution` filled in; raises `ValueError` if there's nothing open to
resolve). New `EscalationRequired(HarnessError)`.

`ImplementStage._implement_one_ticket`: retry-budget exhaustion now records
an `EscalationRecord` and raises `EscalationRequired` instead of a bare
`StageError`; before attempting any ticket, an *open* escalation for that
ticket refuses the attempt outright (no thrash on the same failure every
run), while a *resolved* one folds the human's answer into the bootstrap
prompt and gets a fresh retry budget. Final-acceptance drift also records
an escalation (`kind="drift"`, run-level).

`Orchestrator.run()` catches `EscalationRequired` from `_run_implement` and
returns a clean `OrchestratorResult(halted=True, halt_reason="escalation",
warnings=[...])` instead of letting it surface as a traceback.

`cli.py`: `run` prints a dedicated escalation summary and points at
`harness status`/`harness resolve`, exiting with a distinct code (5,
checked before the generic halted/warnings codes 2/4). `status` lists open
escalations first — what's actually blocking the next run. New `harness
resolve --project <dir> [--ticket <id>] --answer <text>` command.

No deviations.

## T-560 — Status observability: spend, per-stage cost, run history
`journal.py` gained three pure aggregation helpers over `read_run_log()`'s
entry list — no folder access, no IO: `spend_total()`, `spend_by_stage()`
(cost grouped by `stage`), and `calls_by_template()` (grouped by
`(prompt_template, prompt_version)` into a `TemplateStats` — calls, input/
output tokens, cost — the primitive a future prompt-A/B comparison tool
would consume; this ticket only exposes the grouping, per its stated scope).

`harness status` now prints, in order: open escalations (unchanged from
T-530, still first since they block the next run); the current frozen
spec version (`freeze.latest_version()`) and a pipeline-position line per
gated stage (`latest_gate_outcome(folder, stage).decision`, or `"pending"`
if never gated) plus an implement-stage done/pending count from
`progress.json`; total spend vs. `config.budget.max_usd_per_run` with a
"(over warn threshold)" note once `spend_total >= warn_at_usd`, and the
per-stage breakdown; then progress and decisions exactly as before. A
project with no run.log yet prints a plain "Spend: no runs recorded"
rather than a zeroed-out breakdown.

New `harness log --project <dir> [--tail N] [--stage <name>]` pretty-prints
run.log entries (timestamp, stage, model, `template@version`, token counts,
cost) one per line, filtering by stage before applying `--tail` (so `--tail
3 --stage tickets` means "the last 3 tickets-stage calls", not "the last 3
calls, then filtered"). An empty/missing run.log — filtered or not — prints
"no runs recorded" and exits 0, no traceback.

`status` now loads `harness.config.yaml` (previously it didn't touch config
at all) to read `budget.max_usd_per_run`/`warn_at_usd` — every project that
reaches Stage 1 already has a valid config, so this adds no new precondition
in practice.

This was the last ticket in the v0.2 improvement batch (`tickets-v0/000-
overview.md` §8) — all 13 hardening tickets and 7 improvement tickets are
now implemented, tested, and committed.

## T-540 — Deferred-phase ticket archiving + `harness phase` activation
`folder.py` gained `spec_tickets_deferred_dir` /
`spec_tickets_deferred_phase_dir(phase_id)` (`spec/tickets/deferred/<id>/`).
`TicketsStage.run()` now writes every non-active-phase ticket there instead
of discarding it (`filter_active_phase`'s complement), excluded from
`tickets.zip` and from Stage 3's glob (which only reads
`spec/tickets/*.md`) exactly as before — concept §20's "cross-phase ticket
archiving" open item.

New `harness phase --project <dir> [--next | --activate <id>]`: refuses
unless every ticket in the currently-active phase has a `progress.json`
entry and there are no open escalations (both checked before touching
anything), then flips the `active` flag in `phasing.yaml` and moves the
target phase's deferred ticket files from `spec/tickets/deferred/<id>/`
into `spec/tickets/` so the next `harness run` implements them via the
normal Stage 3 path (`plan_build_order()` derives the build order
programmatically from each ticket's own Connections, same as always).
`cli.py run`'s phase-boundary halt message now points at this command.

Deviation: does not regenerate `000-overview.md`'s prose (its dependency-
graph description, written by the model, would go stale after promotion) —
this is intentionally out of scope. Stage 3 never parses the overview's
prose for build order; it always derives it programmatically from each
ticket file's own Connections section, so the promoted tickets execute
correctly regardless of what the overview document says about them.
Regenerating that document would need a model call `harness phase` (a
plain CLI command with no adapter access) cannot make.

## T-240 — End-to-end pipeline test
Added `tests/test_e2e_pipeline.py`, the capstone integration test: drives the
full `Orchestrator` over a temporary project with `FakeTextAdapter` +
`FakeCodingAgent` + a `Sandbox` subclass that never touches Docker — no
network, no containers, no spend. Covers: the full pipeline green end-to-end
(every declared output file exists, including `tickets.zip` and a frozen
spec version); crash-and-resume (a coding agent with an empty script raises
on the first implement call, simulating a crash; a fresh orchestrator with a
working script then completes from the first incomplete unit, without
re-freezing); the budget-exceeded halt path; gate paths (`reject` raises and
halts, `approve` proceeds, `auto_approve` never calls `gate_io`); and the
phase-stop path (a concept declaring `stop_after_active_phase: true` halts
before any coding-agent call).

No deviations.
