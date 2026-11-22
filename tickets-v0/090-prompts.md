# T-090 — Prompt templates + renderer

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/prompts.py`, `src/harness/prompt_templates/`

## Goal
Make every injected prompt a versioned template rendered with stage variables —
never a hard-coded string — so prompts can be optimised, versioned, and (later)
A/B-tested without code changes (concept §15, goal "every injected prompt should
be optimised for an AI").

## Creates / changes
- `prompts.py` — template loader resolving `(name, version)` against the
  configured `template_dir`, with a renderer that substitutes stage variables.
- `prompt_templates/` (package data) — default templates for: Stage 1a
  brainstorm, 1a concept-write, 1a self-review, 1b guidelines, 1b consolidation,
  Stage 2 tickets, Stage 3 bootstrap, Stage 3 review-gate.
- Per-project override via `prompts.template_dir` from config.

## Acceptance criteria
- Each named template loads by name + version; the configured `version` is
  honoured.
- Rendering substitutes provided variables; a missing template or missing
  variable raises a typed error (no silent blanks).
- A project-level `template_dir` overrides the shipped defaults.
- Default templates exist for all eight named prompts (content may be a clearly
  marked first-draft placeholder — see Notes).

## Out of scope
- Optimising prompt *content* (concept §20 open item; best authored as the
  harness's own first ticket) and A/B comparison tooling (v1).

## Connections
- **Depends on:** T-010, T-020.
- **Blocks:** T-170, T-180, T-190, T-200, T-210, T-220.
- **Relates to:** T-030 (`prompts.template_dir`, `version`), T-050 (template +
  version logged per call).

## Testing
**Test-first** for rendering. Cases: load by name/version; variable
substitution; missing-template and missing-variable errors; project override
beats default.

## Notes
Ship minimal, clearly-marked placeholder templates so the pipeline is runnable;
replacing them with optimised drafts is tracked as a follow-up (concept §20).
