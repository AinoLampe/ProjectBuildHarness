# T-160 — Stage contract (base Protocol)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/stages/base.py`

## Goal
Define the single interface every stage implements, which is what makes the
pipeline replayable, resumable, and pure over the folder (concept §5,
guidelines §3).

## Creates / changes
- `stages/base.py` — a `Stage` Protocol / ABC with:
  - `inputs: list[Path]` — the exact files the stage may read.
  - `outputs: list[Path]` — the exact files it produces.
  - `run(folder, adapter, rendered_prompt, ...) -> StageResult` — produces the
    declared outputs and returns artifacts plus any new blocking questions.
  - integration with the folder's declared-IO guard (T-040) so a stage that
    reads/writes an undeclared file fails.

## Acceptance criteria
- The protocol is fully typed; a trivial fake stage satisfies it.
- The stage's *own* minimal surface is `inputs`, `outputs`, `run()`;
  model/agent resolution, prompt rendering, gating, recording, and budgeting are
  explicitly the orchestrator's job (applied *around* the stage), not inside it.
- The declared-IO guard is wired: writing an undeclared file raises a typed
  error; reading an undeclared input raises a typed error.
- `StageResult` can carry new blocking questions (so Stage 1a can re-enter its
  loop).

## Out of scope
- Any concrete stage behaviour (T-170 – T-210).
- Sequencing of stages (orchestrator, T-220).

## Connections
- **Depends on:** T-040, T-100, T-130.
- **Blocks:** T-170, T-180, T-190, T-210, T-220.
- **Relates to:** T-090 (rendered prompts passed in by the orchestrator).

## Testing
**Test-first.** Cases: a fake stage conforms; declared-IO guard rejects
undeclared read and undeclared write; `StageResult` carries blocking questions.
