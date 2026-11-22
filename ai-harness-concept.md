# AI Harness for Project Initialisation — Technical Concept

*Version 1.0 — implementation-ready specification*

This document specifies a system that takes project requirements and drives them
through to a reviewed, tested implementation, with human checkpoints where they
matter and autonomy everywhere else. It is the consolidated design agreed during
the brainstorming phase and is intended to be detailed enough to write tickets
against.

---

## 1. Goals and principles

**Goal.** The user supplies requirements (a document or inline prompt) plus a
local project folder. The harness produces an architectural concept, engineering
guidelines, implementation tickets, and a working implementation of the project
(scoped to the first phase when the requirements imply phasing) — with the user
approving the key milestones.

**Cost principle.** The harness software is free. The only costs are model
inference (tokens), which depend entirely on the models the user selects.
Authentication is either a per-provider API key (pay-per-token) or, for Claude,
a subscription whose non-interactive "Agent SDK credit" covers headless runs
before overflowing to API rates. *Verify current pricing at run time — the
billing model for autonomous usage changed in mid-2026.*

**Design principles** (these shape every decision below):

1. **The project folder is the state.** Nothing important lives only in a chat
   context. Every stage reads files and writes files.
2. **Each stage is a pure function over the folder.** Stage *N* reads the
   artifacts of stage *N−1* and writes its own. This gives free resumability,
   single-stage replay, and trivial "fresh sessions" (a fresh session is just a
   model call whose context is only the declared input files).
3. **Artifacts are the source of truth**, not conversations. The concept is the
   *architectural* source of truth ("what to do"); the guidelines are the
   *engineering* source of truth ("how to do it").
4. **Two sources of truth, one precedence.** When concept and guidelines
   conflict, the concept wins.
5. **Spec freeze before implementation.** The agreed concept + guidelines are
   versioned and locked before any code is written.
6. **Model and agent choice everywhere**, selected per stage via configuration.
7. **Verification beats opinion.** Review gates run automated checks (tests, plus
   lint/types/build where the guidelines define them) *and* an LLM review, never
   an LLM review alone.
8. **Everything is observable and budgeted.** Every model call's prompt, model,
   token count and cost is logged; a per-run budget guard can halt the pipeline.

---

## 2. Architecture overview

```
requirements.md
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR (CLI, external)                                 │
│  - state machine over the project folder                    │
│  - per-stage model/agent routing                            │
│  - human gates, retry budgets, budget guard, run log        │
└─────────────────────────────────────────────────────────────┘
   │            │              │                 │
   ▼            ▼              ▼                 ▼
 Stage 1a     Stage 1b      Stage 2           Stage 3
 Concept  →   Guidelines →  Tickets      →    Implementation
 (+brainstorm)(+consolidate)(overview+DAG)    (agent, sandboxed,
                                               review gates)
   │            │              │                 │
   ▼            ▼              ▼                 ▼
 concept.md   guidelines.md  tickets/*.md      src/ + journal/
```

The orchestrator is a thin external program (Python or TypeScript CLI). It does
not "think" — it sequences stages, curates each stage's input context, calls the
configured model or agent, enforces gates and budgets, and records everything.
This is what makes non-Claude models possible: the concept, guidelines and ticket
stages are ordinary provider-API calls; only the implementation stage shells out
to a coding agent.

---

## 3. Project folder layout

The folder *is* the database. Canonical layout:

```
project/
  requirements.md            # user input (or attached document)
  instructions.md            # optional extra user instructions
  harness.config.yaml        # model/agent routing, gate policy, budgets, sandbox
  spec/
    concept.md               # Stage 1a output — architectural source of truth
    guidelines.md            # Stage 1b output — engineering source of truth
    open-questions.md        # Stage 1a brainstorming exchange (human-in-loop)
    phasing.yaml             # declared phases + active phase (from the concept)
    tickets/
      000-overview.md        # index ticket: DAG, build order, conventions
      010-*.md ...           # one ticket per problem
    .lock/                   # frozen, versioned spec snapshots
  journal/
    DECISIONS.md             # human-readable conflict decisions
    decisions.json           # machine-readable mirror
    PROGRESS.md              # human-readable per-ticket progress
    progress.json            # machine-readable mirror (drives resumability)
    run.log                  # every prompt, model, tokens, cost, artifact hash
  src/                       # the implementation (the only thing the agent writes)
```

A single rule keeps the system honest: **a stage may only read the input files
it declares and may only write the output files it declares.** Everything else is
off-limits to that stage.

---

## 4. Configuration (`harness.config.yaml`)

```yaml
project:
  name: my-project
  root: ./my-project
  requirements: ./my-project/requirements.md
  instructions: ./my-project/instructions.md   # optional

# Model/agent choice is per stage — choice everywhere.
models:
  concept:    { provider: anthropic, model: claude-opus-4-8 }
  guidelines: { provider: anthropic, model: claude-sonnet-4-6 }
  tickets:    { provider: anthropic, model: claude-opus-4-8 }
  implement:  { agent: claude-code,  model: claude-sonnet-4-6 }
  review:     { agent: claude-code,  model: claude-opus-4-8 }   # stronger reviewer

gates:                       # all interactive by default (see §11)
  concept:    interactive    # mandatory
  guidelines: interactive    # may be set to auto_approve
  tickets:    interactive    # review tickets before implementation
  phase_boundary: stop       # stop at the end of a declared phase

brainstorm:
  max_rounds: 3
  on_exhaust: proceed_with_documented_assumptions

implementation:
  order: dependency_graph    # topological sort of the overview DAG
  review:
    require_tests_green: true
    require_llm_review: true
  retry_budget: 2            # attempts per ticket before escalation
  on_exhaust: escalate_to_user

sandbox:
  file_confinement: project_root   # agent cannot read/write outside root
  code_execution: container        # untrusted generated code runs in a container
  network: []                      # [] = offline; or allowed domains, e.g. ["pypi.org"]
  container_image: harness/devcontainer:latest

budget:
  max_usd_per_run: 25
  warn_at_usd: 15

prompts:
  template_dir: ./harness/prompts  # versioned, optimised prompt templates
  version: v1
```

---

## 5. Stage contract and the orchestrator

Every stage implements the same interface, which is what makes the pipeline
replayable and resumable:

| Element        | Definition                                                        |
|----------------|-------------------------------------------------------------------|
| `inputs`       | The exact list of files the stage may read.                       |
| `outputs`      | The exact list of files the stage produces.                       |
| `model/agent`  | Resolved from `harness.config.yaml` for this stage.               |
| `prompt`       | A versioned template rendered with the stage's variables.         |
| `gate`         | Optional human checkpoint after the stage (approve / edit / reject)|
| `record`       | Appends to `run.log` and updates the machine-readable journal.     |

Of these, `inputs`, `outputs` and a `run()` that produces the outputs form the
stage's own (minimal) interface. Model/agent resolution, prompt rendering, the
gate, recording, and budget tracking are the **orchestrator's** responsibilities,
applied *around* each stage rather than implemented inside it.

The orchestrator is a state machine: `concept → guidelines → freeze → tickets →
implement`. Before running any stage it checks the journal; if the stage's
outputs already exist and are unchanged, it is skipped (idempotency). On crash or
manual restart, the orchestrator reads `progress.json` and resumes at the first
incomplete unit of work.

"Fresh session for context management" is implemented structurally: each stage's
model call receives **only** its declared input files. The brainstorming chatter
of Stage 1a never reaches Stage 1b, because Stage 1b's only input is
`concept.md`.

---

## 6. Stage 1a — Architectural concept

**Inputs:** `requirements.md`, optional `instructions.md`.
**Outputs:** `spec/concept.md`, `spec/open-questions.md`, `spec/phasing.yaml`.
**Gate:** interactive (mandatory).

### 6.1 Bounded, structured brainstorming

Before writing anything, the model produces a structured `open-questions.md`
rather than free-form chatter. Each item is categorised and severity-tagged:

```markdown
## Assumptions (proceeding unless corrected)
- [low] Persistence is a single relational DB unless stated otherwise.

## Decisions needed (blocking)
- [high] Auth: session cookies or JWT? Affects the API layer design.

## Suggested improvements (optional)
- [med] Add rate limiting at the gateway; cheap insurance for a public API.
```

The session is **interactive**: the user answers inline and the model
incorporates the answers. The loop is **bounded** by `brainstorm.max_rounds`
(default 3). If unresolved blocking items remain after the cap, the harness does
**not** loop forever — it records explicit assumptions for each open item and
proceeds (`proceed_with_documented_assumptions`). This guarantees termination.

### 6.2 Writing and self-review

1. The model writes `concept.md` once all blocking questions are resolved or
   assumed.
2. It then runs a **self-review pass** checking the concept for inconsistencies,
   gaps, and whether it is specified enough to enable ticket writing. Any *new*
   blocking question discovered here re-enters the interactive loop (still
   subject to the round cap).
3. The concept is "ready" only when it satisfies an explicit readiness checklist
   (see 6.4).

### 6.3 Phasing decision (the concept author decides)

The concept author evaluates whether the requirements imply phasing — for
example because the requirements defer scope to a later development stage, or
because a smaller first version is the sensible deliverable. If so, it:

- declares the phases and their scope inside `concept.md`, and
- writes `spec/phasing.yaml`:

```yaml
phases:
  - id: phase-1
    name: Core MVP
    scope: "Auth, project CRUD, single-user."
    active: true
  - id: phase-2
    name: Collaboration
    scope: "Sharing, real-time editing."
    active: false
stop_after_active_phase: true
```

When `phasing.yaml` declares phasing, the harness implements only the **active
phase** and **stops** at the phase boundary, awaiting a go-ahead. If no phasing
is declared, the run proceeds end-to-end.

### 6.4 Concept readiness checklist (gate criteria)

The concept is approvable only if it specifies: the component breakdown and their
responsibilities; the data model / key entities; external interfaces and
integrations; the technology stack; the major data and control flows; non-
functional constraints (performance, security, scale) where the requirements
imply them; and explicit phasing (or an explicit statement that none is needed).

---

## 7. Stage 1b — Engineering guidelines

**Inputs:** `spec/concept.md` **only** (fresh context — no brainstorming history).
**Outputs:** revised `spec/concept.md` (if consolidation changed it),
`spec/guidelines.md`.
**Gate:** interactive, but may be configured to `auto_approve`.

1. **Generate guidelines** from the concept: general software best practices plus
   guidelines specific to this project's stack and needs, and explicitly
   AI-coding-friendly rules. Meaningful automated tests are mandated by default,
   with a test-first discipline applied where it fits the code, and the review
   gate requires them green. (How strictly test-first applies — versus test-after
   against fakes for thin glue over external systems — is a guideline-level
   refinement per codebase.) Alongside this: conventions for linting/formatting,
   error handling, logging, naming, commit/PR structure, and directory layout.
   This stage is largely autonomous; the user may be consulted but is not
   required.
2. **Consolidation check.** The guidelines and concept are checked for conflicts.
   If any exist, a harmonisation step resolves them — **the concept always wins**
   ("what" outranks "how"). Any change to the concept is recorded.
3. Both artifacts are emitted for later use and added to the project folder.

---

## 8. Spec freeze

After the guidelines gate, the orchestrator snapshots `concept.md` and
`guidelines.md` into `spec/.lock/<timestamp>/` with content hashes recorded in
`run.log`. Stages 2 and 3 reference the **frozen** spec. This prevents silent
drift between what the user approved and what gets built. Re-running an earlier
stage produces a new frozen version and invalidates downstream outputs.

---

## 9. Stage 2 — Writing implementation tickets

**Inputs:** frozen `spec/concept.md`, frozen `spec/guidelines.md`,
`spec/phasing.yaml`.
**Outputs:** `spec/tickets/000-overview.md`, `spec/tickets/0NN-*.md`, plus a
`tickets.zip` added to the project folder.
**Gate:** interactive (review tickets before implementation).

### 9.1 The overview / index ticket (`000-overview.md`)

Written first. It is the index for everything else and defines:

- the **dependency graph** (which ticket blocks / relates to / depends on which),
- the **build order** (a valid topological ordering of the graph),
- the **conventions** every ticket must follow (naming, file locations, testing
  expectations, definition of done).

### 9.2 Ticket schema

Each ticket is a markdown file with at least:

- **Goal** — the single problem this ticket solves.
- **Creates / changes** — the module(s) or files it produces.
- **Acceptance criteria** — objective, testable conditions for "done".
- **Out of scope** — what this ticket explicitly does not do.
- **Connections** — blocks / relates to / depends on (referencing ticket IDs).
- (Optional further sections where useful.)

### 9.3 Granularity rule

**One problem, one ticket.** Each ticket must be independently implementable and
reviewable/testable, sized so it can be completed with **minimal context** — a
single agent session should be able to implement it from the concept, the
guidelines, the overview ticket, and the ticket itself. Tickets that are too
large are split; trivial tickets are merged into their natural neighbour.

### 9.4 Phase scoping

When phasing is declared, Stage 2 writes tickets for the **active phase only**.
Later phases are deferred until their phase becomes active.

---

## 10. Stage 3 — Implementation

**Inputs:** frozen `spec/concept.md`, frozen `spec/guidelines.md`, all
`spec/tickets/*.md`.
**Writes:** `src/`, `journal/DECISIONS.md` (+`decisions.json`),
`journal/PROGRESS.md` (+`progress.json`).
**Agent:** configured coding agent (default: Claude Code via the Agent SDK, run
headlessly with `claude -p`), running inside the sandbox (§12).

### 10.1 Bootstrapping prompt (injected once)

The agent is instructed to read, in order: the concept (architectural source of
truth), the guidelines (engineering source of truth), the overview ticket, then
the remaining tickets — to gain a complete picture before writing code. Conflicts
between documents are resolved by a reasonable decision **documented in
`DECISIONS.md`** (concept outranks guidelines). Anything genuinely ambiguous is
**escalated to the user before proceeding**, not guessed.

### 10.2 Dependency-ordered execution

Tickets are implemented in the **build order** from the overview DAG (topological
sort), not in arbitrary order. This guarantees dependencies exist before their
dependents and opens the door to parallelising independent branches later.

### 10.3 Per-ticket review gate (tests + LLM review)

A ticket is **not** complete until it passes both checks:

1. **Automated checks green (objective).** The ticket's tests must run and pass,
   along with any other automated quality checks the guidelines define (e.g. lint,
   type-checking, build). These are the hard signals that make unattended runs
   trustworthy — for a typed/linted codebase the gate runs them rather than
   trusting the reviewer to eyeball guideline adherence.
2. **LLM review (semantic).** A reviewer (a separate agent/subagent, optionally a
   stronger model) confirms the implementation satisfies the acceptance criteria,
   respects "out of scope", and adhered to the guidelines throughout.

Using a separate reviewer with isolated context — rather than the same agent
grading its own work — is deliberate; the Agent SDK's subagents maintain separate
context per invocation, which fits this exactly.

### 10.4 Retry budget and escalation

If a ticket fails its review gate, the agent retries up to
`implementation.retry_budget` times (default 2). On exhaustion the harness
**stops and escalates to the user** (`escalate_to_user`) with the failure
context, rather than thrashing or shipping a broken ticket.

### 10.5 Journals (human- and machine-readable)

- **DECISIONS.md / decisions.json** — every conflict and the reasoning, so a
  human can audit and the orchestrator can reason about state.
- **PROGRESS.md / progress.json** — one entry per ticket: ticket ID, summary of
  what was implemented, and any deviations from the ticket and why.
  `progress.json` is the basis for crash recovery and resumability.

### 10.6 Final acceptance pass (closing the loop)

After all active-phase tickets pass, a final pass validates the **assembled
implementation against the original `requirements.md`** — not just against the
tickets. Tickets can faithfully implement a concept that has drifted from what the
user actually asked for; this pass catches that. Then a confirmation prompt is
sent to the user.

---

## 11. Human-in-the-loop gates

Gates are **interactive** by default. At each gate the user can **approve**,
**edit** (modify the artifact, then approve), or **reject** (send it back with
feedback). Gate policy is configurable per stage so a trusted, well-understood
project can run more autonomously (e.g. `guidelines: auto_approve`). The phase
boundary is itself a gate: `phase_boundary: stop` halts after the active phase.

| Gate            | Default     | Purpose                                            |
|-----------------|-------------|----------------------------------------------------|
| Concept         | interactive | Mandatory — the spec foundation.                   |
| Guidelines      | interactive | May be auto-approved.                              |
| Tickets         | interactive | Review the plan before code is written.            |
| Phase boundary  | stop        | Pause after the active phase; await go-ahead.      |
| Escalation      | on demand   | Triggered by retry-budget exhaustion or ambiguity. |

---

## 12. Sandboxing

Two distinct concerns, both required because the agent must run the tests (and
therefore execute generated code):

1. **File confinement.** The agent may only read/write inside the project root.
   Enforced via the agent's working-directory restriction and tool allow/deny
   rules (`--allowedTools`, permission rules). This protects the rest of the
   user's machine.
2. **Code-execution isolation.** Because the generated code is untrusted, tests
   and build commands run inside a **container** (a devcontainer/Docker image),
   with the project folder bind-mounted and **network disabled by default** (or
   restricted to an allowlist for dependency installation). The strongest setting
   uses an ephemeral container per run.

`sandbox` in the config selects the level. `network: []` means fully offline;
package installation that needs the registry uses a minimal allowlist.

---

## 13. Model and agent pluggability

A uniform **adapter interface** decouples orchestration from providers:

- **`TextStageAdapter`** (concept, guidelines, tickets): `generate(prompt, files)
  -> GenerationResult`, where the result carries the generated text **and token
  usage** — so the run log (§14) and the budget guard have the numbers they need.
  Implementations: Anthropic, OpenAI, others — each behind the same interface, so
  adding a provider is configuration plus a small adapter, not a rewrite.
- **`CodingAgentAdapter`** (implementation): `run(workdir, prompt, sandbox) ->
  AgentResult`, carrying the outcome plus usage/cost. Implementations: Claude
  Code / Agent SDK (default), OpenCode, others.

Per-stage routing in `harness.config.yaml` means the concept can be written by
one model, tickets by another, and code by a third, including paid-subscription
models where the chosen provider supports it.

---

## 14. Observability, cost and budget

- **run.log** records, for every model/agent call: stage, provider, model,
  prompt template + version, input/output token counts, estimated cost, wall
  time, and the content hash of each artifact written. This is what makes prompt
  optimisation (an explicit project goal) measurable and A/B-testable.
- **Budget guard.** The orchestrator tracks cumulative spend against
  `budget.max_usd_per_run`, warns at `warn_at_usd`, and halts before exceeding the
  cap — important because a multi-stage, multi-model pipeline with review gates
  can be expensive.

---

## 15. Prompt management

Every injected prompt is a **versioned template file** under
`prompts.template_dir`, rendered with stage variables — never a hard-coded
string. This serves the project goal that "every injected prompt should be
optimised for an AI" and lets prompts be improved and compared without code
changes. Templates exist for: Stage 1a brainstorm, Stage 1a concept-write, Stage
1a self-review, Stage 1b guidelines, Stage 1b consolidation, Stage 2 tickets,
Stage 3 bootstrap, and Stage 3 review-gate. (Optimised first drafts of these can
be authored as the first implementation ticket of the harness itself.)

---

## 16. Failure handling and resumability

- **Ambiguity** → ask the user before proceeding (never guess).
- **Conflict between documents** → reasonable decision, recorded in DECISIONS.md.
- **Review-gate failure** → retry up to the budget, then escalate to the user.
- **Crash / interruption** → resume from `progress.json`; completed, unchanged
  units are skipped; the first incomplete unit is re-run.
- **Upstream change** → re-running an earlier stage re-freezes the spec and
  invalidates downstream outputs, forcing a clean rebuild from that point.

---

## 17. Entry point and interface

**CLI first.** It is the fastest path, is scriptable, and maps cleanly onto
interactive gates.

```
harness run    --project ./my-project        # run the full pipeline
harness run    --project ./my-project --from tickets   # resume from a stage
harness status --project ./my-project        # show journal / progress
harness gate   --project ./my-project --approve|--edit|--reject
```

A thin web UI is a later option, justified only once the gate UX (answering
brainstorming questions, reviewing tickets) becomes the bottleneck — not before.

---

## 18. On "a single Claude Skill"

A single chat Skill is the wrong shape for the **whole** harness: a Skill runs in
one Claude context, cannot natively call non-Claude providers, and cannot give
true fresh sessions between stages — which breaks both the model-choice and the
context-management requirements. Skills are, however, the right shape for the
**behaviours inside** the harness (brainstorming, ticket-writing, the review
gate), which become reusable skill/subagent definitions the orchestrator injects.

If an all-Claude version were ever wanted (accepting the loss of multi-provider
choice), the viable form is not a chat Skill but **Claude Code / the Agent SDK as
the orchestrator itself**, using subagents — which carry isolated context — for
each stage. That is a legitimate v0.

---

## 19. Build roadmap for the harness

- **v0 — Walking skeleton.** CLI orchestrator; folder-as-state; Claude for all
  text stages and Claude Code for implementation; interactive gates; file
  confinement + container execution; run.log + budget guard. Single provider.
- **v1 — Pluggability.** Provider adapters (per-stage model choice everywhere);
  OpenCode as an alternative coding agent; prompt template versioning + A/B.
- **v2 — Scale and UX.** Parallel implementation of independent DAG branches;
  optional web UI for gates; richer phase management across multiple phases.

---

## 20. Open items for future refinement

- Concrete container image / devcontainer definition and the network allowlist
  for dependency installation.
- The exact escalation UX (how a stuck ticket is surfaced and handed back).
- Cross-phase ticket archiving (how deferred-phase tickets are stored and later
  activated).
- Optimised first-draft text for each prompt template (best produced as the
  harness's own first ticket).
