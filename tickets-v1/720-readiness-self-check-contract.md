# T-720 — Wire the `ReadinessSelfCheck` contract: structured readiness assessment instead of keyword sniffing

**Phase:** v1 — improvements (approved 2026-09-14)
**Module(s):** `src/harness/stages/concept.py`, `src/harness/contracts.py`,
`src/harness/prompts.py`, `src/harness/prompt_templates/v1/concept_readiness.md` (new)

## Problem
T-500 built `contracts.ReadinessSelfCheck` (per-item booleans + `missing_items()`) but
deferred wiring it (DECISIONS.md T-500). `concept.py` still decides readiness with
`missing_readiness_items()`: a keyword scan of the rendered concept (`"component"`,
`"data model"`, `"tech stack"`, `"phase"`, …). A concept that says "we will decide the
technology stack later" passes the `technology stack` item; one that describes its
components without the word "component" fails; and a failure is a hard `StageError`
that ends the run instead of re-entering the bounded self-review loop the concept
describes (§6.2: a readiness gap is a new blocking question).

## Goal
Readiness is the model's explicit, structured self-assessment against the §6.4
checklist, with evidence, and a failed item re-enters the bounded interview instead of
aborting the stage.

## Creates / changes
- `contracts.py` — `ReadinessSelfCheck` gains `evidence: dict[str, str]` (item → the
  concept excerpt or heading that satisfies it), the ticket's original "yes/no +
  evidence".
- `concept_readiness.md` (new; registered in `NAMED_TEMPLATES`) — given the concept,
  return one `ReadinessSelfCheck` JSON object; an item is `true` only if the concept
  *specifies* it (not "to be decided").
- `stages/concept.py` — after self-review and revision: one `generate` call →
  `parse_structured(..., ReadinessSelfCheck, re_ask=...)`; `missing_items()` non-empty
  → each missing item becomes a blocking question fed into the self-review
  `run_bounded_resolution_loop` instance (still under `brainstorm.max_rounds` — the
  cap is shared, not reset), followed by `concept_revise`; then one final readiness
  call; still missing → `StageError` listing the items (bounded: at most two
  readiness calls per stage run). Delete `READINESS_CHECKLIST` and
  `missing_readiness_items`. The `phasing_decision` item follows T-620's policy
  (`single` → satisfied by an explicit "none needed" statement).
- Consistency test extended.

## Acceptance criteria
- A concept describing components without the word "component" passes (fake
  self-check all true); a concept saying "tech stack to be decided" with a scripted
  `technology_stack: false` re-enters the loop (one more `ask_user` call) and passes
  after revision.
- Still missing after the bounded loop → `StageError` naming the items; at most two
  readiness calls per run.
- `open-questions.md` shows the readiness-derived blocking question(s) (rendered via
  T-630's structure).
- No keyword table remains in `concept.py`.

## Out of scope
- Changing the checklist items themselves (concept §6.4).
- The gate (unchanged).

## Connections
- **Depends on:** T-600, T-630, T-170, T-350, T-500.
- **Blocks:** none.
- **Relates to:** T-620, T-550.

## Testing
**Test-first.** Cases: pass/fail routing from scripted self-checks; re-entry consumes
the shared cap; bounded call count; template variables.
