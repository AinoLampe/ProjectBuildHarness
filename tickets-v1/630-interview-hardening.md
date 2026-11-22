# T-630 — Interview hardening: structured per-item answers, suggestions tracked, Q&A fidelity, draft-concept input, usable CLI input

**Phase:** v1 — improvements (approved 2026-09-14)
**Module(s):** `src/harness/stages/concept.py`, `src/harness/contracts.py`,
`src/harness/cli.py`, `src/harness/config.py`, `src/harness/folder.py`,
`src/harness/prompt_templates/v1/` (`brainstorm.md`, `concept_self_review.md`,
`concept_write.md`, `concept_revise.md`)

## Motivation
R3 (an interview routine with a configurable round cap) is already met by
`run_bounded_resolution_loop` and `brainstorm.max_rounds` (T-170/T-350). Four defects
blunt it:
1. **Answers without questions.** `ConceptStage.run()` collects only the user's answer
   strings (`resolutions.append(answer)`) and hands `"\n\n".join(resolved)` to
   `concept_write` as `{{resolved_questions}}` — the writer sees "JWT" or "2. yes,
   3. no" with no question text. The transcript exists (it is fed back to the
   *brainstorm* rounds since T-350) but never reaches the concept writer.
2. **Only blocking items are handled.** The loop terminates on "no bullets under
   `## Decisions needed`"; assumptions and suggested improvements are shown, but
   nothing records whether the user accepted or rejected them, so "proposes
   improvements" has no follow-through and a wrong assumption survives unless the user
   spots it in free text.
3. **T-500 left `OpenQuestions` unwired.** `parse_blocking_questions` still matches the
   `## decisions needed` heading string — the misparse class T-500 exists to remove.
4. **CLI input is one line.** `_interactive_ask_user` is a single `typer.prompt("> ")`:
   a round with five questions must be answered in one line, and the interactive gate's
   `edit` asks for a whole replacement artifact in one `typer.prompt`.
R1 additionally asks for "a concept with requirements" as input. A user-supplied draft
concept has no entry point: a pre-placed `spec/concept.md` is gated as-is by T-320's
logic and the run later fails on the missing `phasing.yaml`.

## Goal
The interview is structured item by item (ids, decisions, multi-line answers), every
item's fate is recorded, the concept writer receives the questions with the answers,
and a user-supplied draft concept enters the same interview instead of being rewritten
from scratch (concept v1.1 §6.1).

## Creates / changes
- `contracts.py` — `QuestionItem` gains `id: str` (`A-1…`, `Q-1…`, `S-1…`, assigned
  by the model per the template); `InterviewRound` (= `OpenQuestions` + `round: int`);
  `InterviewAnswers(items: list[ItemDecision])` with `ItemDecision(id, decision:
  Literal["answer","accept","reject","defer"], text: str = "")`. `brainstorm.md` and
  `concept_self_review.md` demand the `OpenQuestions` JSON, parsed with
  `parse_structured` (one bounded re-ask); `open-questions.md` is rendered from the
  structure by `render_open_questions_md`.
- `stages/concept.py` — `ask_user: Callable[[InterviewRound], InterviewAnswers]`.
  Loop semantics: blocking items still decide termination; an assumption marked
  `reject` becomes a blocking question in the next round (the model is told so via the
  transcript); `accept`/`reject` on a suggestion → `DecisionRecord` ("suggestion S-n
  accepted/rejected: …", ticket `None`) and accepted suggestions are listed for the
  writer; `defer` records "deferred to a later increment" (R2 wording). The text
  handed to `concept_write` as `{{resolved_questions}}` is rendered as `Q: … / A: …`
  pairs plus accepted suggestions plus documented assumptions (name kept, content
  changed). `run_bounded_resolution_loop` keeps its shape, typed over the structures.
- Draft concept — `config.py` `ProjectConfig.concept_draft: Path | None = None`;
  `folder.py` resolves it; when set, `ConceptStage` declares it as an input, skips
  `concept_write`, renders `{{draft_concept}}` into `brainstorm.md` ("interview the
  draft: gaps, contradictions, missing readiness items"), and `concept_revise` folds
  the answers into the draft (revise, not rewrite); self-review and readiness proceed
  unchanged; a `DecisionRecord` names the draft path.
- `cli.py` — `_interactive_ask_user` iterates the round's items: prints id, severity,
  text; prompts per item (`answer` / `accept` / `reject` / `defer`; blank = accept for
  assumptions and suggestions, text required for blocking questions); a `!edit` reply
  opens `click.edit()` for multi-line text. `harness run --answers-file <json>`
  supplies `InterviewAnswers` per round for scripted runs (an exhausted file is an
  error, never silence). The interactive gate's `edit` decision opens
  `click.edit(artifact)` instead of a one-line prompt; `harness gate --edit <path>` is
  unchanged.
- Templates — `brainstorm.md`/`concept_self_review.md` (ids + JSON schema),
  `concept_write.md` (Q/A pairs + accepted suggestions), `concept_revise.md` gains a
  draft-mode paragraph and `{{draft_concept}}` handling. Consistency test extended.

## Acceptance criteria
- A fake-scripted round with one assumption, one blocking question and one suggestion:
  `reject` of the assumption yields a blocking question in round 2's prompt; `accept`
  of the suggestion yields a `DecisionRecord` and the suggestion text appears in the
  `concept_write` prompt; the blocking answer appears **with its question text** in
  the `concept_write` prompt.
- `open-questions.md` is rendered from the validated structure and stays
  human-readable (three sections, ids, severities).
- `brainstorm.max_rounds` semantics unchanged: exactly N answer opportunities,
  documented assumptions on exhaustion — the T-350 tests pass against the structured
  loop.
- With `project.concept_draft` set: no `concept_write` call; the draft text is in the
  brainstorm prompt; the written `concept.md` is the revised draft; `phasing.yaml` and
  `open-questions.md` exist afterwards.
- CLI: an `--answers-file` run answers every item without a TTY (`CliRunner`); the
  interactive gate `edit` path calls `click.edit` (monkeypatched) and writes its return
  value.

## Out of scope
- The readiness self-check contract (T-720).
- Any change to the guidelines stage's autonomy (concept §7 unchanged).
- A web UI for the interview (concept §17, later).

## Connections
- **Depends on:** T-600, T-610, T-170, T-230, T-320, T-350, T-500, T-550.
- **Blocks:** T-680, T-720.
- **Relates to:** T-620.

## Testing
**Test-first** for the structured loop (decision routing, rejected-assumption
promotion, transcript rendering, exhaustion), `render_open_questions_md`, draft mode;
CLI via `CliRunner` with `click.edit` monkeypatched; fakes emit the JSON forms.
