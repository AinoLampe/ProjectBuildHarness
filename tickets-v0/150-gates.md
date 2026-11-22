# T-150 — Interactive gates (approve / edit / reject)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/gates.py`

## Goal
Implement the human-in-the-loop checkpoints: at each gate the user can approve,
edit-then-approve, or reject-with-feedback, with per-stage policy
(`interactive` / `auto_approve`) and the phase-boundary `stop` (concept §11).

## Creates / changes
- `gates.py`:
  - present an artifact and accept `approve` / `edit` (modify, then approve) /
    `reject` (return feedback to the caller).
  - honour per-stage policy from config: `interactive`, `auto_approve` (skip the
    prompt), and `phase_boundary: stop` (halt after the active phase).
  - signal rejection via `GateRejected` carrying the feedback.
  - IO is injected (prompt/response handles) so it is testable without a TTY.

## Acceptance criteria
- `approve` → proceed; `edit` → the artifact is updated then proceeds; `reject`
  → caller receives the feedback (no proceed).
- `auto_approve` proceeds without prompting; `stop` halts at the phase boundary.
- Rejection raises/returns `GateRejected` with feedback attached.
- Fully testable with injected IO (no real terminal needed).

## Out of scope
- The web UI (v2).
- The Stage 1a brainstorming Q&A loop — that interactive exchange lives inside
  the concept stage (T-170); this module is the approve/edit/reject gate.

## Connections
- **Depends on:** T-020, T-040.
- **Blocks:** T-220, T-230.
- **Relates to:** T-170/T-180/T-190 (gated stages).

## Testing
**Test-first** with injected IO. Cases (incl. guidelines §4.4 "gate rejection"):
approve; edit-then-approve; reject returns feedback; auto_approve; stop.
