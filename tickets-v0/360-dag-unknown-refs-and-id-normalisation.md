# T-360 — Typed error for unknown DAG references + ticket-id normalisation across stages

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/dag.py`, `src/harness/stages/tickets.py`,
`src/harness/stages/implement.py`

## Problem
1. **Untyped crash.** `topological_order()` raises a bare `KeyError` when a
   `depends_on`/`blocks` entry references an id not in the node set
   (`add_edge` → `successors[prerequisite]`). Reproduced:
   `topological_order([TicketNode(id='020', depends_on=['010'])])` →
   `KeyError: '010'`. Guidelines §3 requires specific typed exceptions. This
   is reachable in production: an active-phase ticket that depends on a
   deferred-phase ticket (filtered out by `filter_active_phase`) crashes
   Stage 2 with a `KeyError`.
2. **Id-format lottery.** The stages disagree about id shape, so a model that
   writes ids any way other than bare `NNN` breaks ordering:
   - `tickets.py` keys nodes by bare header ids (`"020"`); a Connections line
     of `depends on: T-010` yields the unknown id `"T-010"` → `KeyError`.
   - `implement.py::_parse_ids` blindly prefixes `T-`: a ticket file whose
     Connections say `T-020` becomes `"T-T-020"` → `KeyError`.
   - References to the overview (`000`) are excluded from the node set → also
     `KeyError`.

## Goal
Unknown references fail with a helpful, typed error naming the offending
ticket and reference; equivalent id spellings (`010`, `T-010`,
`010-some-slug`) normalise to one canonical form everywhere.

## Creates / changes
- `dag.py` — validate all edge endpoints before building edges; raise a new
  `DagReferenceError(HarnessError)` (or extend `DagCycleError`'s module with
  it) naming the referencing node and the unknown id. Log the addition in
  `DECISIONS.md` per the T-090 precedent.
- A single `normalise_ticket_id()` helper (in `dag.py`) used by both
  `tickets.py::parse_tickets_response` and `implement.py::parse_ticket_file`:
  strips a `T-` prefix and any `-slug` suffix, yielding the canonical `NNN`
  (implement.py may re-add its `T-` display prefix after normalising).
- `tickets.py::validate_build_order` — validate over the **full** parsed
  ticket set first (catching cross-phase and dangling references with the
  typed error), then order the scoped set with cross-phase edges dropped
  (a dependency satisfied by an earlier, deferred phase is not a cycle).

## Acceptance criteria
- Unknown reference → typed error naming referencer + missing id; no
  `KeyError` escapes `dag.py`.
- `depends on: T-010`, `010`, and `010-core-primitives` all resolve to the
  same node.
- Active-phase ticket depending on a deferred-phase ticket: Stage 2 succeeds,
  the cross-phase edge is dropped from ordering, and the fact is recorded in
  the journal (visibility, not a crash).
- References to `000` (overview) are ignored for ordering, not fatal.

## Out of scope
- Changing the ticket schema itself (T-520 adds fields).
- Cycle detection semantics (unchanged).

## Connections
- **Depends on:** T-080, T-190, T-210.
- **Blocks:** none.
- **Relates to:** T-500 (structured ticket output makes ids machine-checked at
  generation time).

## Testing
**Test-first.** Cases: unknown ref → typed error with names; each id spelling
normalises; cross-phase dependency dropped + journaled; overview refs ignored;
existing cycle/empty/diamond cases unchanged.
