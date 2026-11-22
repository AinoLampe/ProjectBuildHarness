# T-350 — Brainstorm loop: feed the user's answers back to the model; fix the round cap

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/stages/concept.py`,
`src/harness/prompt_templates/v1/brainstorm.md`,
`tests/unit/test_concept_logic.py`, `tests/unit/test_concept_stage.py`

## Problem
Concept §6.1: "The session is interactive: the user answers inline and **the
model incorporates the answers**." In `run_bounded_resolution_loop` /
`ConceptStage.run()`:

1. **Answers never reach the model.** `generate_brainstorm_questions()` renders
   the same prompt from only `requirements`/`instructions` every round — the
   accumulated `resolutions` are not passed in. Against a real model the same
   blocking questions regenerate every round, the cap always exhausts, and
   every blocking item degrades to a "documented assumption" even though the
   user answered it. (The fake adapter scripts different responses per call,
   which masked this.) The self-review loop has the same defect, and its
   resolutions are merely appended verbatim as a "## Self-review resolutions"
   section instead of being incorporated into the concept text.
2. **Off-by-one on the cap.** With `max_rounds = 3` the user is asked only
   **twice** (`rounds >= max_rounds` fires on entry to round 3); with
   `max_rounds = 1` the user is never asked at all and the loop goes straight
   to documented assumptions.

## Goal
Each brainstorm/self-review round shows the model the prior questions and the
user's answers; the user gets exactly `max_rounds` answer opportunities before
exhaustion.

## Creates / changes
- `concept.py`:
  - `run_bounded_resolution_loop` passes the accumulated Q&A transcript into
    `generate_questions` (signature becomes
    `Callable[[str], str]` taking the transcript-so-far).
  - fix the cap: `ask_user` is called up to `max_rounds` times; assumptions
    are recorded only if blocking items remain **after** the final answered
    round.
  - self-review: after resolutions, ask the model for a **revised concept**
    incorporating them (one extra generate call), replacing the raw append.
- `brainstorm.md` template gains a `{{qa_transcript}}` variable ("empty on the
  first round"); `concept_self_review.md` analogously.

## Acceptance criteria
- A scripted fake proves round N's prompt contains round N−1's questions and
  the user's answer.
- `max_rounds = 3` → up to 3 `ask_user` calls; `max_rounds = 1` → exactly 1
  before assumptions.
- Termination guarantee unchanged: with perpetually-blocking scripted
  responses the loop exits via documented assumptions.
- Self-review resolutions produce a coherent revised concept (fake-scripted),
  not an appended Q&A dump.

## Out of scope
- Structured (JSON) question/answer format — T-500 owns the output contract.
- Prompt content optimisation (T-550).

## Connections
- **Depends on:** T-170.
- **Blocks:** none.
- **Relates to:** T-500, T-550.

## Testing
**Test-first.** Cases: transcript accumulation reaches the prompt; cap
semantics for max_rounds ∈ {1, 2, 3}; exhaustion still terminates; revised
concept replaces append.
