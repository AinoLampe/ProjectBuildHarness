# T-640 — Epics in Stage 2: epic plan, tickets per epic, the closure rule, epic-aware build order

**Phase:** v1 — increments, epics, review dialogue
**Module(s):** `src/harness/stages/tickets.py`, `src/harness/contracts.py`,
`src/harness/dag.py`, `src/harness/stages/implement.py` (`parse_ticket_file`,
`plan_build_order`), `src/harness/folder.py`, `src/harness/core/errors.py`,
`src/harness/cli.py` (`status`), `src/harness/prompt_templates/v1/` (`epic_plan.md`,
`epic_tickets.md` new; `tickets.md` retired)

## Motivation
R4: tickets should be grouped into epics that suit AI implementation and need minimal
context. Today Stage 2 is one model call returning every ticket as free text split on a
`## TICKET:` regex (the tickets half of T-500's contract conversion was deferred —
DECISIONS.md T-500), and Stage 3 walks one flat topological order. There is no unit
between "ticket" and "the whole increment" for an end-to-end test (R6) to attach to,
no way to bound a ticket-writing call to one coherent slice, and the `### Tests`
section T-520 wanted mandatory is still optional because the freeform parser could not
enforce it.

Binding definitions (concept v1.1 §9; `000-overview.md` §2, confirmed 2026-09-14):
- **Epic** — a vertically cohesive slice of the concept delivering one externally
  observable capability (a feature, a bounded context, or a foundation such as
  scaffolding/tooling), verifiable on its own by an end-to-end acceptance test that
  can only pass once all of its tickets are done. 3–10 tickets; every ticket belongs
  to exactly one epic; **always at least one epic** — a small project is one epic, so
  "create epics only when it makes sense" becomes "the model decides how many,
  minimum one" and Stage 3 stays uniform.
- **Epic DAG** — epics may depend on epics; acyclic. Epics are *not* required to be
  independent (that would force foundations to be duplicated); epics with no path
  between them are parallelisable at epic level (v2).
- **Closure rule** — a ticket may depend on a ticket of another epic only if its epic
  declares a dependency on that epic. Ticket edges inside an epic are free.

## Goal
Stage 2 produces an epic plan and, per epic, a focused ticket set — both as validated
contracts — and the build order is "epics in topological order, tickets in topological
order within each epic".

## Creates / changes
- `contracts.py` — `Epic(id: str ("E01"…), slug, goal, capability,
  acceptance_scenarios: list[str] (≥ 1, Given/When/Then style, observable through the
  capability's public interface), depends_on_epics: list[str], definition_of_done:
  str)`; `EpicPlan(overview_md: str, epics: list[Epic])` (≥ 1 epic, acyclic checked
  at validation); `TicketItem` gains `epic: str` and `tests: list[str]` (≥ 1 path —
  T-520's mandatory `### Tests`); `TicketSet` keeps its shape; ids validated as
  `\d{3}`; connections normalised at validation via `normalise_ticket_id`.
- `stages/tickets.py` — two-level generation: (1) one `epic_plan` call (frozen concept
  + guidelines, frozen project state, phasing) → `EpicPlan`, written as
  `spec/tickets/000-overview.md` (the model's overview prose **plus** a
  harness-rendered "Epics" section: epic order and, once known, each epic's ticket
  ids) and `spec/tickets/epics/E0N-<slug>.md` (rendered from `Epic`); (2) one
  `epic_tickets` call per epic in epic order (frozen concept + guidelines, project
  state, the overview, the epic file, the ids and one-line goals of tickets already
  written for earlier epics, the next free ticket number) → `TicketSet`; ticket files
  `spec/tickets/0NN-<slug>.md` rendered from `TicketItem` with mandatory `### Epic`,
  `### Tests` and `### Connections` sections. Ids are global 3-digit, allocated
  sequentially in build order (`010, 020, …`). Validation (pure, test-first): every
  ticket names a known epic; every epic has ≥ 1 ticket; epic DAG acyclic
  (`dag.topological_order` over epic nodes); ticket refs exist (`DagReferenceError`);
  closure rule (`EpicClosureError`, naming ticket, target ticket and both epics);
  ticket DAG acyclic. `filter_active_phase` applies unchanged (phase tags optional;
  dormant under T-620). `tickets.zip` includes `epics/`. Regeneration feedback (T-320)
  is applied to the epic-plan call and all ticket calls re-run after a rejected
  overview.
- `core/errors.py` — `EpicClosureError(HarnessError)`.
- `dag.py` — algorithm unchanged; add `topological_order_grouped(groups: dict[str,
  list[TicketNode]], group_deps: dict[str, list[str]]) -> list[tuple[str, list[str]]]`
  (group order, then node order within each group; `DagCycleError`/
  `DagReferenceError` at either level).
- `stages/implement.py` — `TicketSpec.epic`; `parse_ticket_file` reads `### Epic`
  (`StageError` if missing — no silent default); new `parse_epic_file(path, text) ->
  EpicSpec` (id, depends_on_epics, ticket ids, scenarios); `plan_build_order(specs,
  epics) -> list[tuple[str, list[str]]]` via `topological_order_grouped`; the loop
  iterates epics then tickets — behaviour otherwise unchanged in this ticket (the
  epic gate is T-670).
- `folder.py` — `spec_tickets_epics_dir`, `spec_epic_md(epic_id)`.
- `cli.py` — `status` lists epics with ticket counts done/pending.
- Templates — `epic_plan.md` (definition, sizing, closure rule, ≥ 1 epic, scenario
  rules, JSON schema), `epic_tickets.md` (granularity rule, schema incl. `tests` and
  `epic`, id allocation, connections format, the minimal-context rule: a ticket must be
  implementable from concept + guidelines + overview + its epic file + itself);
  `tickets.md` removed from `NAMED_TEMPLATES`. Consistency test extended.

## Acceptance criteria
- Fake-scripted plan with two epics (E02 depends on E01) and five tickets: files
  written under `spec/tickets/` and `spec/tickets/epics/`; `000-overview.md` lists the
  epic order and ticket ids per epic; `tickets.zip` contains all; build order is E01's
  tickets (topologically) then E02's.
- A single-epic plan works identically (no special casing anywhere).
- Closure violation (an E02 ticket depends on an E01 ticket while E02 does not depend
  on E01) → `EpicClosureError` naming both tickets and epics; cyclic epic
  dependencies → `DagCycleError`; unknown ticket ref → `DagReferenceError`; a ticket
  without `tests` or `epic` → `StageError` from contract validation after one bounded
  re-ask.
- Each epic's ticket call receives only: frozen concept + guidelines, project state,
  the overview, its own epic file, and earlier epics' ids + goals (fake-adapter prompt
  assertion) — never other epics' full ticket texts.
- Stage 3 (`parse_ticket_file`/`parse_epic_file`/`plan_build_order`) orders a mixed
  on-disk ticket set by epic then ticket; a ticket file without `### Epic` fails
  loudly.
- All existing Stage 2 behaviours hold under the contracts: overview first, phase
  filtering, DAG validation, gate-rejection regeneration, zip; the e2e pipeline test's
  fake script is updated for `1 + number of epics` Stage 2 calls.

## Out of scope
- The epic gate, acceptance-test units and `journal/epics/` (T-670).
- Epic-level parallel execution (v2).
- Re-planning epics after implementation has started.

## Connections
- **Depends on:** T-600, T-610, T-080, T-190, T-210, T-360, T-500, T-520, T-550.
- **Blocks:** T-670, T-680.
- **Relates to:** T-620, T-560.

## Testing
**Test-first** for the contracts, validation (closure, cycles, refs, mandatory
sections), grouped ordering, rendering round-trips (structure → markdown →
`parse_ticket_file`/`parse_epic_file`); **fake-adapter** for the two-level generation
(call count = 1 + number of epics; prompt contents per call).
