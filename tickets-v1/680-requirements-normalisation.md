# T-680 — Stage 0a requirements normalisation: a structured, traceable form of the user's requirements for every downstream prompt

**Phase:** v1 — increments, epics, review dialogue (added 2026-09-18)
**Module(s):** new `src/harness/stages/requirements.py`, `src/harness/contracts.py`,
`src/harness/folder.py`, `src/harness/config.py`, `src/harness/orchestrator.py`,
`src/harness/freeze.py`, `src/harness/stages/concept.py`,
`src/harness/stages/tickets.py`, `src/harness/stages/implement.py`,
`src/harness/cli.py`, `src/harness/prompt_templates/v1/`
(`requirements_normalise.md` new; `survey_summarise.md`, `brainstorm.md`,
`concept_write.md`, `epic_plan.md`, `final_acceptance.md` gain variables)

## Motivation
`requirements.md` is whatever the user wrote: prose, bullets, an e-mail, or a whole
draft concept (R1). It is pasted verbatim into the survey, brainstorm and concept
prompts, and the final acceptance pass judges the build against it as one block of
text. Three things are lost that way: (1) there are no stable requirement ids, so
nothing downstream — epics, tickets, the final pass — can say *which* requirement it
delivers or misses, and "did we build everything?" stays a holistic guess (T-410's
known weakness); (2) goals, constraints, nice-to-haves and background reach the model
in one undifferentiated shape, so the structured outputs the pipeline now demands
(T-500, T-630, T-640) rest on an unstructured base; (3) ambiguities are discovered
only inside the brainstorm, with no record of what the input itself left open.

The user asked whether an "optimise the prompt" step right after submission makes
sense. It does — under one condition this ticket makes binding: **the step may
restructure the requirements, never reinterpret them.** A silent rewrite would turn
the ground truth into an LLM artifact before the pipeline starts (concept §10.6
measures the build against the *original* requirements, and that must stay so).
Hence: the original is never modified and remains the authority; the normalised form
is a derived, gated artifact in which every item quotes its source sentence, nothing
may be added, and anything unclassifiable is shown to the user instead of dropped
(concept v1.1 §6.0.1).

## Goal
A Stage 0a that turns `requirements.md` into `spec/requirements-normalised.md`
(+ `.json`): stable ids, one verifiable statement per requirement, kind and priority,
verbatim source quotes, flagged ambiguities — gated by the user, frozen with the spec,
and consumed by the survey, the interview, the concept writer, the epic planner
(coverage) and the final acceptance pass (per-requirement verdict).

## Creates / changes
- `contracts.py` — `RequirementItem(id: "R-NNN", kind: Literal["functional",
  "non_functional","constraint","interface","data","quality"], text: str (one
  imperative, verifiable statement), source: str (verbatim quote of the original
  sentence(s)), priority: Literal["must","should","could"] = "must" (lowered only
  when the original says so), acceptance_hint: str)`; `FlaggedAmbiguity(id: "AMB-N",
  requirement_ids: list[str], question: str)`; `NormalisedRequirements(language: str,
  title: str, summary: str, goals: list[str], requirements: list[RequirementItem]
  (≥ 1), out_of_scope: list[str] (only what the original states), glossary:
  dict[str, str], ambiguities: list[FlaggedAmbiguity], unclassified: list[str])`.
- `stages/requirements.py` — `RequirementsStage` (`Stage` protocol; inputs:
  `requirements.md`, optional `instructions.md`, optional `project.concept_draft`
  (T-630) as a second source whose items carry `source: "draft: …"` quotes; outputs:
  the two artifacts). Pure, test-first logic: `split_atoms(text) -> list[str]`
  (sentences and bullets of the original); `check_coverage(original_atoms, items) ->
  CoverageReport` (an atom is *covered* when some item's `source` matches it by
  normalised substring or ≥ 0.6 token overlap; an item is *grounded* when its
  `source` matches an atom the same way); `render_normalised_md(model, report) ->
  str` (sections in the order above plus "Not classified — please check" for
  uncovered atoms and "Unsourced — possible invention" for ungrounded items).
  `run()`: `requirements.mode: model` → one text-stage call rendered from
  `requirements_normalise.md` (rules: keep the original language; restructure, never
  reinterpret; one statement per requirement; no new requirements — an inferred need
  becomes an ambiguity; quote sources verbatim; priorities only when stated), parsed
  with `parse_structured` (one bounded re-ask that also carries the coverage report so
  the model can repair gaps); `mode: passthrough` → no model call, one
  `RequirementItem` per atom with `kind: functional`, `source == text`, no
  ambiguities. A `DecisionRecord` is written when ungrounded items or uncovered atoms
  remain after the re-ask (visible in the artifact and at the gate; not fatal).
- `folder.py` — `spec_requirements_normalised_md` / `spec_requirements_normalised_json`.
- `config.py` — `RequirementsConfig(mode: Literal["model","passthrough"] = "model")`
  as `HarnessConfig.requirements`; `GatesConfig.requirements: GatePolicy =
  "interactive"` (a rewrite can shift meaning, so the default is to show it);
  `ModelsConfig.requirements: ModelRoute | None = None` (defaults to the `concept`
  route; a text route with a budget rate like the others, T-370).
- `orchestrator.py` — after `_ensure_increment()` (T-620) and before the survey:
  `_ensure_stage_gated("requirements", spec_requirements_normalised_md,
  gates.requirements, self._generate_requirements)`; run-logged under stage
  `"requirements"`, template `requirements_normalise`, through
  `_RecordingTextAdapter`. `invalidate_from("requirements")` moves both artifacts
  aside plus everything downstream; `_STAGE_ARTIFACTS` gains `requirements` (first).
  The increment id stays the hash of the **original** `requirements.md` (T-620);
  T-620's archive list gains the two artifacts.
- `freeze.py` — the normalised markdown is frozen with the spec (manifest
  `requirements_hash`; old manifests load with `None`), so epics and tickets reference
  ids that cannot drift.
- Consumers — `survey_summarise.md` and `brainstorm.md` receive `{{requirements}}` =
  the normalised markdown; `brainstorm.md` also gets `{{flagged_ambiguities}}`
  ("include these among the round-1 blocking questions unless the requirements
  already answer them"); `concept_write.md` gets `{{requirements}}` (normalised) and
  `{{original_requirements}}` (verbatim, for nuance); `epic_plan.md` (T-640): `Epic`
  gains `requirement_ids: list[str]` and Stage 2 validation checks that every `must`
  requirement id is covered by ≥ 1 epic — uncovered ids trigger one bounded re-ask of
  the epic-plan call, then `StageError` naming them; `final_acceptance.md` (T-650):
  keeps `{{requirements}}` = the **original** as the authority and gains
  `{{requirement_checklist}}` (ids + texts); the reviewer must return one `drift`
  finding per unmet requirement with `location: R-NNN`, so the verdict is per
  requirement instead of holistic. `ImplementStage` declares the frozen normalised
  file as an input for that pass.
- `cli.py` — `harness run --from requirements`; `status` shows the requirement count
  by priority, flagged ambiguities and the gate state.
- Templates — `requirements_normalise.md` (new); the five consumer templates gain the
  variables above. Consistency test extended.

## Acceptance criteria
- Fake-scripted normalisation of a three-bullet requirements file: ids `R-001…R-003`
  with verbatim sources, the markdown rendered in the section order above, both
  artifacts written, the run.log entry under stage `requirements`, and the interactive
  gate shown (`gate_io` called with the rendered markdown); `gates.requirements:
  auto_approve` skips it.
- Coverage: an original sentence that no item quotes appears under "Not classified";
  an item whose `source` is not in the original appears under "Unsourced"; both
  trigger exactly one re-ask (whose prompt names the atoms/items) and, if still
  present afterwards, a `DecisionRecord` — never a silent drop and never a crash.
- `requirements.mode: passthrough`: no adapter call; one item per atom; downstream
  stages run unchanged.
- `requirements.md` is byte-identical before and after the stage (never modified);
  the increment id is unaffected by normalisation (T-620 test extended).
- The brainstorm prompt contains the normalised markdown and the flagged ambiguities;
  the concept prompt contains both the normalised and the original text; the survey
  prompt uses the normalised text (fake-adapter assertions).
- Epic coverage: a plan leaving a `must` requirement uncovered → one re-ask, then
  `StageError` naming the id; a covered plan writes `requirement_ids` into each epic
  file.
- Final acceptance: a scripted reviewer verdict with a `drift` finding at `location:
  R-002` surfaces as the run-level drift escalation naming `R-002` (T-650 path); the
  original requirements text is still that template's `{{requirements}}` variable.
- `harness run --from requirements` moves the two artifacts and everything downstream
  aside; a hand-edit of the approved normalised file re-gates it (T-320 hash rule)
  and, once approved, re-freezes and invalidates downstream (T-330 rule).
- A draft concept (T-630) as second source yields items with `draft:` sources
  (fake-scripted).

## Out of scope
- Resolving ambiguities (the interview's job, T-630 — this stage only flags them).
- Translating the requirements (the original language is kept).
- Per-ticket requirement ids (epics carry them; tickets inherit through their epic).
- Editing `requirements.md` on the user's behalf (a changed original is a new
  increment, T-620).

## Connections
- **Depends on:** T-600, T-610, T-620, T-630, T-640, T-650, T-090, T-100, T-320, T-330, T-370, T-500.
- **Blocks:** none.
- **Relates to:** T-410, T-550, T-560, T-700.

## Testing
**Test-first** for `split_atoms`, `check_coverage` (substring and token-overlap
matching; uncovered/ungrounded classification), `render_normalised_md`, the
passthrough mode, the epic coverage validation and the orchestrator sequencing /
`--from` behaviour; **fake-adapter** for the model path (call count 1, or 2 with the
re-ask; prompt contents per consumer); template consistency test extended.
