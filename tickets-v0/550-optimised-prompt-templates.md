# T-550 — Optimised prompt templates (replace the eight first-draft placeholders)

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/prompt_templates/v1/*` (revised in place — see
Note), `tests/unit/test_prompts.py`

## Motivation
Concept §15 and §20: "every injected prompt should be optimised for an AI",
with optimised first drafts "best produced as the harness's own first ticket".
All eight shipped templates are still marked `FIRST-DRAFT PLACEHOLDER`. Beyond
generic thinness, several have concrete functional gaps:

- `implement_bootstrap.md` tells the agent to read "the frozen concept, the
  frozen guidelines, the overview ticket" **without any paths** — the agent
  cannot know `spec/.lock/<version>/` without being told the version. It also
  restates journal obligations vaguely rather than naming
  `journal/DECISIONS.md` semantics.
- `review_gate.md` gives the reviewer no paths to the concept/guidelines
  (T-140 specifies they be included), no explicit acceptance-criteria rubric,
  and no instruction on how to weigh out-of-scope violations.
- `tickets.md` does not state the granularity rule, the connections id
  format, or the requirement that the overview define conventions — the
  things Stage 2 *validates*, so today the validator is stricter than the
  instructions.
- `brainstorm.md` / `concept_self_review.md` lack the transcript variable
  (T-350) and any output contract (T-500).

## Creates / changes
- Rewrite all eight templates against their stage's *validated expectations*:
  every structure a stage parses or validates must be explicitly demanded by
  the template (single source: T-500's contracts).
- New variables where stages have the data but don't pass it:
  `implement_bootstrap` gains `{{frozen_concept_path}}`,
  `{{frozen_guidelines_path}}`, `{{overview_path}}`, `{{journal_dir}}`;
  `review_gate` gains `{{concept_path}}`, `{{guidelines_path}}`,
  `{{acceptance_criteria}}` (extracted section, not the whole ticket).
- Stage code updated to supply the new variables (mechanical).
- A "template ↔ stage expectation" test: for each template, assert its
  placeholders exactly match the variables the stage supplies (catches
  drift in either direction) — replacing today's render-only checks.

## Acceptance criteria
- No template contains the `FIRST-DRAFT PLACEHOLDER` marker.
- Bootstrap and review prompts contain resolvable paths (fake-driven run
  asserts the frozen version's real path appears in the prompt the adapter
  receives).
- Placeholder/variable exact-match test covers all templates and fails on
  either an unused variable or an unsupplied placeholder.
- Full fake pipeline (T-240) green with the new templates.

## Note on versioning
These land as a revision of `v1` *before* any real-run baseline exists — there
is nothing meaningful to A/B against yet, and `v1` has never produced a real
artifact. The first *post-baseline* optimisation must instead create `v2/`
(the version mechanism exists precisely for that).

## Out of scope
- A/B comparison tooling (v1 roadmap).
- Structured-output schemas themselves (T-500 defines them; this ticket
  embeds them in prose).

## Connections
- **Depends on:** T-090, T-350, T-400, T-500.
- **Blocks:** none.
- **Relates to:** T-410 (its two new templates follow the same standard).

## Testing
**Test-first** for the placeholder/variable exact-match harness; fake-driven
end-to-end as regression.
