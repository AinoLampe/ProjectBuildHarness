# T-400 — Wire the dead config knobs (prompts.*, implementation.review.*, sandbox.*)

**Phase:** v0.1 — hardening (post-review)
**Module(s):** `src/harness/orchestrator.py`, `src/harness/stages/review.py`,
`src/harness/stages/implement.py`, `src/harness/cli.py`

## Problem
Several documented `harness.config.yaml` settings are parsed, validated…and
then silently ignored — the config lies to the user:

1. **`prompts.template_dir` / `prompts.version`** — `prompts.py` implements
   the override (T-090 acceptance: "a project-level template_dir overrides the
   shipped defaults"), but the orchestrator constructs every stage
   (`ConceptStage`, `GuidelinesStage`, `TicketsStage`, `ImplementStage`)
   without passing either — all stages always use the shipped `v1` defaults.
   Concept §15's "prompts can be improved without code changes" is therefore
   unreachable from a project.
2. **`implementation.review.require_tests_green` /
   `require_llm_review`** — `run_review_gate` and `ImplementStage`
   never read them; both checks are unconditionally on. (Unconditional is a
   fine *default*, but a knob that does nothing must either work or not
   exist.)
3. **`sandbox.file_confinement` / `sandbox.code_execution`** — never read by
   anything (T-380 adds the fields that matter; these two literals should be
   consumed or documented as fixed-in-v0).

## Goal
Every field a valid config accepts observably changes behaviour, or is
rejected/documented as fixed.

## Creates / changes
- `orchestrator.py` — pass `config.prompts.version` and
  `config.prompts.template_dir` (resolved relative to the **project root**,
  not the CWD) into every stage constructor; also pass them to
  `run_review_gate` via `ImplementStage`.
- `review.py` / `implement.py` — honour the two review-policy flags:
  `require_tests_green: false` skips the objective block (LLM review still
  runs), `require_llm_review: false` skips the reviewer (objective checks
  still gate). Both `false` → gate passes trivially with a loud journal
  warning.
- `config.py` — resolve/normalise `prompts.template_dir` against the project
  root at load time; document `sandbox.file_confinement`/`code_execution` as
  fixed v0 literals in the field docstrings (they already reject other
  values).

## Acceptance criteria
- A project `template_dir` containing an overriding `v1/brainstorm.md` is
  used by a fake-driven run (proven by asserting the override text reaches
  the adapter); `prompts.version: v2` selects `v2/` templates.
- `require_llm_review: false` → reviewer adapter never called, objective
  checks still enforced; `require_tests_green: false` → sandbox checks never
  run, reviewer still called; both-false emits a journal warning.
- Relative `template_dir` behaves identically regardless of the CWD the CLI
  is invoked from.

## Out of scope
- New sandbox fields (T-380).
- Budget config validation (T-370).

## Connections
- **Depends on:** T-030, T-090, T-200, T-220.
- **Blocks:** T-550 (template iteration needs the override path working).
- **Relates to:** T-380, T-370.

## Testing
**Test-first.** Cases: override dir + version reach every stage; each review
flag combination; CWD-independence of relative template_dir.
