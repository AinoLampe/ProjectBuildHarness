# T-600 — Concept amendment v1.1: increments, project survey, epics, review dialogue, epic gate

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `ai-harness-concept.md` (repository root; no code)

## Motivation
The concept is the architectural source of truth and wins every conflict (concept §1
principle 4; guidelines §5). The six v1 requirements (`000-overview.md` §1) change the
architecture: the input gains a project state; requirements become immediate-only,
which conflicts with §6.3's licence to defer scope into phases; Stage 2 gains epics;
Stage 3's "retry budget" (§10.4) becomes a bounded implementer/reviewer dialogue with
structured findings; a new epic gate appears. Writing code against the unamended
concept would put every later ticket in conflict with the spec it must obey — the
harness's own rule is spec freeze before implementation (principle 5). This ticket is
the v1 batch's "Stage 1a": the amended concept is gated by the user before any code
ticket starts.

## Goal
Amend `ai-harness-concept.md` to version 1.1 so that every v1 ticket can cite the
section it implements, with a changelog and no dangling references.

## Creates / changes
Edit in place (version line → "Version 1.1", `## Changelog` section appended listing
every amended section with a one-line reason):
- **§1 Goals** — input is requirements (or a user-supplied draft concept) **plus the
  current project folder, empty or not**; one run implements one *increment* (one
  immediate requirements document); later versions are new increments over the
  now-existing project.
- **§2 Architecture** — Stage 0 (requirements normalisation, T-680, then the project
  survey) precedes Stage 1a; the state machine is `requirements → survey → concept →
  guidelines → freeze → tickets → implement`.
- **§3 Layout** — add `spec/requirements-normalised.md` + `.json` (T-680),
  `spec/project-state.md` + `.json`, `spec/increment.json`,
  `spec/checks.yaml` (T-700), `spec/tickets/epics/E0N-<slug>.md`,
  `spec/tickets/epics/E0N/acceptance/` (pending e2e tests), `spec/.history/<increment>/`,
  `journal/tickets/<ticket-id>/round-NN-{resolution,review}.{json,md}`,
  `journal/epics/<epic-id>/`, `tests/e2e/<epic-id>/` (activated acceptance tests).
- **§4 Config** — `project.mode`, `project.concept_draft`, `gates.requirements`,
  `models.requirements`, `requirements.mode` (T-680), `gates.survey`,
  `implementation.phasing`, `implementation.max_review_rounds` (replaces
  `retry_budget`, kept as a deprecated alias), `implementation.blocking_severities`,
  `implementation.epics.acceptance_tests`, `sandbox.agent_network`,
  `sandbox.agent_in_container`, `sandbox.agent_env_passthrough`.
- **§5 Stage contract** — Stage 0 listed; the survey's input is "the project tree" (the
  one declared-input exception, read through the inventory walker); the normalised
  requirements and the survey are frozen with the spec (§8).
- **New §6.0 Stage 0** — §6.0.1 requirements normalisation (T-680): the original
  `requirements.md` is never modified and stays the authority; the normalised form is a
  derived, gated, frozen artifact with ids, kinds, priorities, verbatim source quotes,
  flagged ambiguities and a coverage report; restructure, never reinterpret. §6.0.2
  project survey: inputs, outputs, the greenfield rule (`000-overview.md` §2), the gate
  (`interactive`, skipped automatically for a greenfield folder), the read-only agent
  call.
- **§6.1 Interview** — per-item decisions (answer / accept / reject / defer); accepted
  suggestions and rejected assumptions are recorded as decisions; a rejected
  assumption becomes a blocking question; the draft-concept input path (T-630);
  ambiguities flagged by Stage 0a seed the first round.
- **§6.3 Phasing** — default is **single-phase**: all requirements are in scope now and
  the concept must not defer scope; phasing exists only under
  `implementation.phasing: concept_decides`. State explicitly how R2 closes §20's
  cross-phase archiving item (no deferred tickets in `single` mode; later versions are
  increments).
- **§9 Stage 2** — two-level generation (epic plan, then tickets per epic); the epic
  definition, sizing (3–10 tickets, always ≥ 1), the epic DAG and the closure rule;
  epic files with acceptance scenarios and the requirement ids they deliver, plus a
  coverage check that every `must` requirement is planned (T-680); mandatory
  `### Tests` and `### Epic` ticket sections; build order = epics then tickets.
- **§10.3–§10.4** — replace "retry budget" with the **review dialogue**: rounds,
  `ResolutionReport`, `ReviewFindings` with ids/severity/status, fix-or-argue per
  finding, the reviewer settles disputes, blocking severities, round cap → escalation
  **with proposals**; fresh IA/RA processes per round with the round artifacts as
  memory; objective-check failures become synthetic findings and skip the reviewer
  turn; the implementer no longer writes `DECISIONS.md` itself (its report carries the
  decisions; the orchestrator is the single journal writer); an implementer's open
  question is an `ambiguity` escalation before any review (§10.1 unchanged: never
  guess).
- **§10.6 Final acceptance** — still judged against the **original** `requirements.md`;
  now per requirement id (one `drift` finding per unmet id, T-680).
- **New §10.7 Epic gate** — the acceptance-test unit at epic start (pending location,
  expected red recorded), the gate at epic end (activate, objective checks, reviewer
  epic review), the `E0N::close` dialogue on failure, escalation kind `epic_gate`; the
  final acceptance pass gains the objective component "all epic tests green".
- **§11 Gate table** — add the requirements gate, the survey gate, the epic gate, and
  "escalation with proposals" (`harness resolve --choose`).
- **§12 Sandboxing** — agent-network allowlist distinct from the test network; opt-in
  in-container agent (T-740).
- **§16 Failure handling** — a new increment while escalations are open is refused;
  round-level crash-and-resume.
- **§17 CLI** — `harness survey`, `harness resolve --choose N`, `status` additions,
  `harness run --answers-file`, `harness run --from requirements`.
- **§19 Roadmap** — v1 = this batch; provider pluggability / OpenCode → v1.x; parallel
  epics → v2.
- **§20 Open items** — remove cross-phase archiving (closed by R2) and the escalation
  UX (T-530); add: epic-level parallelism, non-Python toolchains in the container
  image, per-domain network allowlist enforcement.

## Acceptance criteria
- Every `§` citation in `tickets-v1/6*.md` and `tickets-v1/7*.md` resolves to a section
  of the amended concept that describes what the citing ticket implements (scriptable:
  grep the citations, check the headings exist).
- No remaining statement that the concept author may defer scope into phases by
  default; `single` is the documented default and `concept_decides` the documented
  opt-in.
- The changelog lists every amended section with a one-line reason.
- The user has approved the amended concept, recorded as a `DecisionRecord` in
  `harness/journal/DECISIONS.md` naming T-600 and the approval date, **before** any
  T-6xx/T-7xx code ticket is started.

## Out of scope
- Any code or test change.
- Rewriting `harness-v0-guidelines.md` (its §7 consolidation note is updated only if a
  conflict is found while amending; the concept wins).

## Connections
- **Depends on:** none.
- **Blocks:** T-610, T-620, T-630, T-640, T-650, T-660, T-670, T-680, T-700, T-710, T-720, T-740.
- **Relates to:** T-530, T-540.

## Testing
Not applicable (documentation ticket). Verification is the acceptance criteria above;
the citation check can be scripted and kept as a small test under `tests/unit/` only
if the concept file is packaged with the repository — otherwise run it by hand and
note the result in `PROGRESS.md`.
