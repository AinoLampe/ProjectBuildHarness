# T-040 — Project-folder access (the state)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/folder.py`

## Goal
Provide typed access to the project folder, which **is** the state (concept §3):
canonical paths, safe typed read/write, and enforcement of the single rule that a
stage may only read its declared inputs and write its declared outputs.

## Creates / changes
- `folder.py` — `ProjectFolder` over a root, exposing typed paths for the whole
  canonical layout: `requirements.md`, `instructions.md`,
  `spec/{concept,guidelines,open-questions}.md`, `spec/phasing.yaml`,
  `spec/tickets/`, `spec/.lock/`, `journal/{DECISIONS.md,decisions.json,
  PROGRESS.md,progress.json,run.log}`, `src/`.
- Typed read/write helpers (text + JSON), creating parent dirs on write.
- A declared-IO guard: given a stage's declared `inputs`/`outputs`, verify reads
  and writes stay within them.

## Acceptance criteria
- Every canonical path from concept §3 is exposed from a root.
- Reading a missing **required** file raises `FolderError`; writes create missing
  parent directories.
- The declared-IO guard rejects a read/write outside the declared set ("a stage
  may only read the input files it declares and may only write the output files
  it declares").
- Pure path logic uses no real clock/network; tmp-folder fixtures provided.

## Out of scope
- Snapshotting/hashing the spec (T-070).
- Journal *content* semantics (T-050) — folder only exposes the paths and raw
  read/write.
- Sandboxing of code execution (T-120).

## Connections
- **Depends on:** T-010, T-020.
- **Blocks:** T-050, T-070, T-100, T-120, T-150, T-160, and every stage.
- **Relates to:** T-080 (reads ticket files), T-220.

## Testing
**Test-first.** Cases: all paths resolve; missing-required-file error;
parent-dir creation; declared-IO guard accepts declared and rejects undeclared
access; JSON round-trip helpers.
