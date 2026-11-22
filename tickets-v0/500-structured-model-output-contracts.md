# T-500 — Structured model-output contracts (stop regex-scraping prose)

**Phase:** v0.2 — improvements (post-review)
**Module(s):** `src/harness/stages/concept.py`, `stages/guidelines.py`,
`stages/tickets.py`, `src/harness/prompt_templates/v1/*`, new
`src/harness/contracts.py`

## Motivation
The pipeline's correctness currently hangs on regex/keyword scraping of
free-form model prose, which is exactly where multi-stage agent pipelines rot:

- Blocking questions: heading string match (`"## decisions needed"`).
- Readiness: keyword sniffing (`"tech stack"` etc.) — a concept mentioning
  "phase" anywhere passes the phasing check.
- Consolidation: `_NO_CONFLICT_PHRASES` exact-match — a model answering
  "No conflicts found." (not verbatim `"no conflict"`) is recorded as a
  **conflict**, generating a spurious DECISIONS entry and possibly rewriting
  the concept.
- Tickets: `## TICKET:` header regex; Connections line regex; phase as a
  loose `### Phase` section.

Each is a silent-misparse waiting for a differently-phrased model. The fix is
one pattern applied everywhere: every prompt that feeds a *parser* must demand
a machine-validatable structure, validated by pydantic, with one bounded
re-ask on violation.

## Creates / changes
- `contracts.py` — pydantic response models: `OpenQuestions` (assumptions /
  blocking / suggestions, each with severity), `ReadinessSelfCheck` (explicit
  per-checklist-item yes/no + evidence), `ConsolidationVerdict`
  (`conflict_found: bool` first-class), `TicketSet` (id, slug, phase,
  connections as typed lists, body). A shared
  `parse_structured(text, model_cls, *, re_ask)` helper: extract the JSON
  block, validate; on failure, one re-ask with the validation error appended;
  then raise `StageError`.
- Templates updated to demand the corresponding JSON structure (fenced JSON
  block after the human-readable markdown, or JSON-only where no human reads
  the intermediate).
- Stages swap their regex parsing for the contracts; the markdown artifacts
  (`open-questions.md`, ticket files) are *rendered from* the validated
  structures, so files stay human-readable while parsing stays exact.
- Readiness check becomes the model's structured self-assessment validated
  against the §6.4 checklist (keyword sniffing deleted).

## Acceptance criteria
- "No conflicts found." parses as *no conflict*; no spurious decision entry.
- A malformed structured response triggers exactly one re-ask, then a typed
  `StageError` carrying the validation error.
- Ticket ids/connections arrive typed — no Connections-regex in
  `tickets.py`; T-360's normalisation applies at validation time.
- All existing stage behaviours (phase filtering, DAG validation, overview
  first) hold, driven by fakes emitting the structured formats.
- `open-questions.md` and ticket `.md` files remain human-readable markdown.

## Out of scope
- Reviewer-verdict extraction from the CLI envelope (T-340).
- Prompt-content optimisation beyond the structural change (T-550).

## Connections
- **Depends on:** T-170, T-180, T-190; benefits from landing after T-350.
- **Blocks:** T-550 (optimised prompts build on the contracts).
- **Relates to:** T-360, T-410.

## Testing
**Test-first.** Golden-path parse per contract; each historical misparse case
(the "No conflicts found." case verbatim); re-ask-then-error path; rendering
round-trip (structure → markdown → human-readable).
