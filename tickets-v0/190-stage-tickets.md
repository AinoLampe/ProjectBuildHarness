# T-190 — Stage 2: Writing implementation tickets

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/tickets.py`

## Goal
Implement Stage 2: from the frozen spec, write the overview/index ticket and one
ticket per problem for the **active phase only**, following the ticket schema and
granularity rule (concept §9).

## Creates / changes
- `stages/tickets.py` implementing the `Stage` contract.
  - **Inputs:** frozen `spec/concept.md`, frozen `spec/guidelines.md`,
    `spec/phasing.yaml`.
  - **Outputs:** `spec/tickets/000-overview.md`, `spec/tickets/0NN-*.md`, plus a
    `tickets.zip`.
  - Write `000-overview.md` **first**: the dependency graph, a valid build order,
    and the conventions every ticket must follow (definition of done, naming,
    file locations, testing expectations).
  - Write each ticket to the schema (Goal / Creates-changes / Acceptance criteria
    / Out of scope / Connections, plus optional sections).
  - Apply **one problem, one ticket** granularity (split the too-large, merge the
    trivial) and **active-phase scoping**.

## Acceptance criteria
- Reads the **frozen** spec (by hash, T-070), not a live copy.
- The overview ticket is written first and defines the DAG, build order, and
  conventions.
- Every produced ticket follows the schema; ordering validates against `dag.py`
  (T-080) — no cycles, valid topological order.
- Only active-phase tickets are written; later phases are deferred.
- `tickets.zip` is produced and added to the folder.
- Driven with `FakeTextAdapter`.

## Out of scope
- Implementing the tickets (T-210).
- Cross-phase ticket archiving/activation (concept §20 open item).

## Connections
- **Depends on:** T-160, T-090, T-100, T-070, T-040.
- **Blocks:** T-220.
- **Relates to:** T-080 (validates the produced DAG).

## Testing
**Test-first** for schema/granularity/active-phase/DAG-validity checks;
**fake-adapter** for generation. Cases: overview written first; produced DAG
acyclic + orderable; active-phase-only scoping; zip emitted.
