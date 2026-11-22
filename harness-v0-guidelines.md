# Engineering Guidelines — Harness v0 (Python)

*Version 1.0 — the engineering source of truth for building the v0 harness.*

These guidelines govern **how** the v0 harness is built. The
[technical concept](./ai-harness-concept.md) remains the architectural source of
truth (**what** is built). Where this document and the concept conflict, the
**concept wins**, and the harmonisation is recorded in `DECISIONS.md`.

This is, deliberately, a manual run of the harness's own Stage 1b: we are
authoring by hand the guidelines artifact the harness would later generate. The
harness mandates TDD and a tests-green review gate, so its own codebase is held
to that same bar — that is the credibility test for the tool.

---

## 1. Tech stack and tooling

| Concern            | Choice                          | Notes                                   |
|--------------------|---------------------------------|-----------------------------------------|
| Language           | Python **3.12+**                | Modern typing, `match`, better generics.|
| Env + dependencies | **uv**                          | Fast, lockfile-based. Poetry acceptable.|
| Lint + format      | **ruff** (lint *and* format)    | Single tool; CI-enforced.               |
| Type checking      | **pyright** or `mypy --strict`  | **Strict mode is mandatory.**           |
| Tests              | **pytest** (+ `pytest-cov`)     | Coverage is a diagnostic, not a gate.   |
| Config + schemas   | **pydantic v2**                 | Validates config and journal JSON.      |
| CLI                | **typer**                       | Type-driven commands.                   |
| Subprocess / agent | stdlib `subprocess`             | Wraps `claude -p`; Docker via CLI.      |
| Logging            | stdlib `logging` → JSON lines   | `run.log` is structured (one JSON/line).|

**Execution model for v0 is synchronous.** The pipeline is sequential, so async
buys nothing yet. Async/parallel DAG branches are explicitly deferred to a later
harness version.

---

## 2. Project structure (src layout)

Module boundaries mirror the components in the concept, so a ticket can be
implemented with minimal context — one ticket touches roughly one module.

```
harness/
  pyproject.toml
  src/harness/
    cli.py            # typer entry points (run, status, gate)
    config.py         # pydantic config model + loader/validator
    folder.py         # project-folder paths + typed read/write (state access)
    orchestrator.py   # state machine over the folder; runs stages
    journal.py        # run.log + DECISIONS/PROGRESS (+ json mirrors)
    freeze.py         # spec snapshot + content hashing
    dag.py            # ticket DAG parse, cycle detection, topological sort
    budget.py         # cost accounting + guard
    gates.py          # interactive gate handling (approve/edit/reject)
    prompts.py        # versioned template loader + renderer
    prompt_templates/ # default *.md / *.j2 template files (package data;
                      #   overridable per project via prompts.template_dir)
    sandbox.py        # file confinement + container code-execution
    stages/
      base.py         # Stage contract (Protocol): inputs, outputs, run()
      concept.py      # 1a    guidelines.py # 1b
      tickets.py      # 2     implement.py  # 3
    adapters/
      text.py         # TextStageAdapter protocol
      anthropic_text.py
      coding.py       # CodingAgentAdapter protocol
      claude_code.py  # claude -p wrapper
  tests/
    unit/             # behavior tests for pure logic
    contract/         # adapter contract tests
    fakes/            # FakeTextAdapter, FakeCodingAgent, tmp project folders
```

---

## 3. Coding standards

- **Typed throughout.** Public functions and methods carry full type hints;
  strict type-checking passes with no ignores except where justified by an inline
  comment naming the reason.
- **Stages are pure functions over the folder.** A stage reads only its declared
  inputs and writes only its declared outputs. No stage reaches into another
  stage's files or carries hidden in-memory state between stages.
- **Side effects live behind adapters.** All network, subprocess, and container
  interaction is isolated behind the `TextStageAdapter` / `CodingAgentAdapter`
  protocols and `sandbox.py`. Business logic never calls a provider SDK or
  `subprocess` directly — it calls an adapter. This is the seam that makes the
  logic testable and the providers swappable.
- **The frozen spec is immutable.** Once `freeze.py` snapshots the spec, nothing
  rewrites it. Downstream stages read the frozen copy by hash.
- **Determinism is injected, not assumed.** Clock, UUID, and any randomness are
  passed in (or behind a small `Clock`/`IdGen` interface) so behavior is
  reproducible and tests are stable.
- **Explicit over implicit.** No module-level mutable globals; config is passed
  in, not re-read ad hoc. Errors are raised as specific, typed exceptions, not
  bare `Exception`, and never silently swallowed.
- **Small surface per change.** Single-purpose modules with explicit typed
  interfaces — this is what lets a coding agent (and a human reviewer) work a
  ticket without loading the whole codebase into context.

---

## 4. Testing strategy

TDD is applied **where it fits**, not ceremonially. The rule is honest about this
codebase rather than mandating test-first uniformly and watching it get ignored
on the glue.

### 4.1 Test-first (write the failing test, then the code)

Apply to the deterministic logic with clear inputs and outputs — the heart of the
harness:

- `dag.py` — topological sort, cycle detection, build-order generation.
- `config.py` — validation, defaults, rejection of malformed config.
- `journal.py` — write/read round-trips, and the resume-from-`progress.json`
  logic.
- `freeze.py` — snapshot + hash + invalidation.
- `budget.py` — cost accumulation, warn/halt thresholds.
- `orchestrator.py` — stage sequencing, gate handling, idempotent skip-on-unchanged.
- `prompts.py` — template rendering with variables.

### 4.2 Test-after, against fakes / contract tests

Apply to the thin glue over external systems, where "test-first" would mostly mean
testing your own mocks:

- Provider adapters (`anthropic_text.py`), the `claude -p` wrapper
  (`claude_code.py`), and `sandbox.py` container execution.
- These are validated by **contract tests**: a shared suite that any adapter
  implementation must pass against a double, ensuring every adapter honors its
  protocol's behavior identically. The real adapters are smoke-tested separately.

### 4.3 Fakes enable end-to-end pipeline tests

`tests/fakes/` provides a `FakeTextAdapter` and `FakeCodingAgent` so the
orchestrator's full pipeline can be exercised — concept → guidelines → freeze →
tickets → implement — **without real models, containers, or spend**. These fakes
are the workhorse for orchestration tests.

### 4.4 What counts as a meaningful test

The harness's review gate requires *tests green*, so "meaningful" must be defined
or the gate is hollow:

- A test asserts on **observable behavior / outputs**, not implementation details.
- A test must **fail if the behavior regresses** — a test that can't fail is not a
  test.
- **No vacuously-passing tests** to satisfy the gate.
- Edge cases are covered explicitly: empty DAG, cyclic DAG, missing input files,
  budget exceeded mid-run, crash-and-resume, gate rejection, retry-budget
  exhaustion.
- **Coverage is measured (`pytest-cov`) but not gated on a line percentage.** The
  bar is behavioral: every public behavior has a behavior-level test.

---

## 5. Workflow constraints

- **One ticket → one small change set → one PR.** Each PR maps to exactly one
  ticket and references its ID.
- **Commit messages** follow a conventional style and name the ticket
  (`feat(dag): topological sort with cycle detection [T-040]`).
- **DECISIONS.md (+ `decisions.json`)**: whenever a conflict or ambiguity is
  resolved during the build, record it — what was decided and why. Concept
  outranks guidelines in any conflict.
- **PROGRESS.md (+ `progress.json`)**: one entry per completed ticket — ticket ID,
  summary of what was implemented, and any deviations from the ticket and why.
  The journals are maintained **even though humans are building v0**, so that
  resumability and the journal format are exercised for real (dogfooding).
- **Definition of done** (per ticket): acceptance criteria met; tests meaningful
  and green; ruff and the type checker clean; journals updated; nothing
  implemented that the ticket marked out of scope.

### Review gate (applied to the harness's own construction)

Mirroring the gate the harness enforces on its targets, a ticket is complete only
when: (1) lint + strict types are clean, (2) its tests are green, and (3) a
reviewer confirms the change meets the acceptance criteria and respects
out-of-scope. We hold building the harness to exactly the standard the harness
imposes.

---

## 6. AI-coding-friendly rules

Because the harness exists to be driven by coding agents, its own codebase is
written to be agent-friendly — which, conveniently, also makes it
human-friendly:

- Explicit, typed interfaces at every module boundary, so a single ticket is
  implementable from the concept, the guidelines, the overview ticket, and the
  ticket itself — nothing more.
- Pure logic separated from side effects, so behavior can be implemented and
  tested in isolation.
- Deterministic, injected dependencies (clock, IDs), so generated tests are
  reproducible rather than flaky.
- No hidden global state and no implicit configuration reads, so an agent can
  reason locally about one module without surprises elsewhere.

---

## 7. Consolidation note

These guidelines were checked against the technical concept. No conflicts were
found at authoring time. Should implementation surface a conflict, the concept
prevails and the resolution is logged in `DECISIONS.md`.
