# T-240 — End-to-end pipeline test (fakes)

**Phase:** v0 — Walking skeleton
**Module(s):** `tests/` (e2e), using `tests/fakes/`

## Goal
Exercise the whole orchestrator across `concept → guidelines → freeze → tickets →
implement` with no real models, containers, or spend — the workhorse test that
proves the v0 skeleton actually walks (guidelines §4.3).

## Creates / changes
- An end-to-end test that drives the full pipeline over a temporary project
  folder using `FakeTextAdapter` (T-100) and `FakeCodingAgent` (T-130).
- Assertions on each stage's declared outputs, the journals, the freeze, resume,
  budget halt, and the gate paths.

## Acceptance criteria
- The full pipeline runs **green** end-to-end with fakes (no network, no Docker).
- Each stage's declared output files exist with the expected shape.
- The crash-and-resume path is covered (resume from `progress.json`).
- The budget-exceeded path is covered (pipeline halts).
- Gate paths are covered: reject, approve, and `auto_approve`.
- The phase-stop path is covered (stops after the active phase).

## Out of scope
- Real-provider smoke tests (those live with T-110 / T-140).
- Performance / load testing.

## Connections
- **Depends on:** T-220, T-100, T-130, T-170, T-180, T-190, T-210.
- **Blocks:** none (validation capstone).
- **Relates to:** every stage and the orchestrator.

## Testing
This ticket **is** the test. It must fail if any stage regresses; no vacuous
passes. It is the integration counterpart to the per-module test-first suites.
