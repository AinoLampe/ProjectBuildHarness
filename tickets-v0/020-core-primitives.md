# T-020 — Core primitives (Clock, IdGen, exception hierarchy)

**Phase:** v0 — Walking skeleton
**Module(s):** `src/harness/core/clock.py`, `core/ids.py`, `core/errors.py`

## Goal
Provide the injected-determinism seams (clock, id generation) and the typed
exception hierarchy that the rest of the codebase depends on, so behaviour is
reproducible and errors are specific (guidelines §3).

## Creates / changes
- `core/clock.py` — `Clock` protocol with `now()`; `SystemClock` (real) and
  `FrozenClock` (deterministic, advanceable) implementations.
- `core/ids.py` — `IdGen` protocol; `UuidGen` (real) and `SeqIdGen`
  (deterministic, e.g. `id-0001`) implementations.
- `core/errors.py` — `HarnessError` base plus specific subclasses:
  `ConfigError`, `FolderError`, `StageError`, `BudgetExceeded`, `GateRejected`,
  `SandboxError`, `AdapterError`, `DagCycleError`.

## Acceptance criteria
- `Clock` and `IdGen` are typed Protocols, each with a real and a deterministic
  implementation.
- `FrozenClock` returns a fixed time and advances predictably; `SeqIdGen`
  produces a deterministic, monotonic sequence.
- All exceptions descend from `HarnessError`; no bare `Exception` is raised.
- Strict types clean; no module-level mutable global state.

## Out of scope
- Wiring these into other modules (each consuming ticket injects them).
- Logging/serialisation of errors (journal owns that, T-050).

## Connections
- **Depends on:** T-010.
- **Blocks:** T-030, T-040, T-050, T-060, T-070, T-080, T-090, T-100, T-120,
  T-150, T-160.
- **Relates to:** every module that injects a clock or raises a typed error.

## Testing
**Test-first.** Cases: `FrozenClock` fixed/advancing; `SeqIdGen` determinism;
exception hierarchy (subclasses catchable as `HarnessError`).
