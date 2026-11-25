"""Test-first: pure loop/readiness/termination/phasing logic for Stage 1a
(T-170), independent of any adapter."""

import pytest

from harness.core.errors import StageError
from harness.stages.concept import (
    extract_phasing_yaml,
    missing_readiness_items,
    parse_blocking_questions,
    run_bounded_resolution_loop,
)

OPEN_QUESTIONS_WITH_BLOCKING = """
## Assumptions (proceeding unless corrected)
- [low] Single relational DB.

## Decisions needed (blocking)
- [high] Auth: cookies or JWT?
- [med] Rate limiting?

## Suggested improvements (optional)
- [low] Add caching.
"""

OPEN_QUESTIONS_NO_BLOCKING = """
## Assumptions (proceeding unless corrected)
- [low] Single relational DB.

## Decisions needed (blocking)

## Suggested improvements (optional)
- [low] Add caching.
"""

READY_CONCEPT = """
# Concept

## Components
Auth service, API gateway.

## Data Model
User, Project entities.

## External Interfaces
REST API, Stripe integration.

## Technology Stack
Python, Postgres.

## Data and Control Flows
Request flows through the gateway.

## Phasing
```yaml
phases:
  - id: phase-1
    name: MVP
    scope: core
    active: true
stop_after_active_phase: true
```
"""


def test_parse_blocking_questions_extracts_only_the_blocking_section() -> None:
    items = parse_blocking_questions(OPEN_QUESTIONS_WITH_BLOCKING)
    assert items == ["[high] Auth: cookies or JWT?", "[med] Rate limiting?"]


def test_parse_blocking_questions_empty_when_section_has_none() -> None:
    assert parse_blocking_questions(OPEN_QUESTIONS_NO_BLOCKING) == []


def test_missing_readiness_items_empty_for_a_complete_concept() -> None:
    assert missing_readiness_items(READY_CONCEPT) == []


def test_missing_readiness_items_flags_absent_sections() -> None:
    incomplete = "# Concept\n\nJust some prose, no structure."
    missing = missing_readiness_items(incomplete)
    assert "component breakdown and responsibilities" in missing
    assert "technology stack" in missing


def test_extract_phasing_yaml_parses_the_fenced_block() -> None:
    phasing = extract_phasing_yaml(READY_CONCEPT)
    assert "active: true" in phasing
    assert "stop_after_active_phase: true" in phasing


def test_extract_phasing_yaml_accepts_explicit_no_phasing_statement() -> None:
    concept = "# Concept\n\n## Phasing\nNo phasing is needed for this project.\n"
    phasing = extract_phasing_yaml(concept)
    assert "phases: []" in phasing


def test_extract_phasing_yaml_raises_when_phasing_section_is_missing() -> None:
    with pytest.raises(StageError):
        extract_phasing_yaml("# Concept\n\nNo phasing section at all.")


def test_extract_phasing_yaml_rejects_multiple_active_phases() -> None:
    concept = """## Phasing
```yaml
phases:
  - id: phase-1
    name: A
    scope: x
    active: true
  - id: phase-2
    name: B
    scope: y
    active: true
stop_after_active_phase: true
```
"""
    with pytest.raises(StageError):
        extract_phasing_yaml(concept)


def test_bounded_loop_terminates_immediately_when_no_blocking_items() -> None:
    def generate_questions(_transcript: str) -> str:
        return OPEN_QUESTIONS_NO_BLOCKING

    def ask_user(_questions: str) -> str:
        raise AssertionError("should never be asked when there are no blocking items")

    text, resolutions = run_bounded_resolution_loop(
        generate_questions=generate_questions, ask_user=ask_user, max_rounds=3
    )
    assert text == OPEN_QUESTIONS_NO_BLOCKING
    assert resolutions == []


def test_bounded_loop_resolves_via_user_answers_until_clear() -> None:
    call_count = {"n": 0}

    def generate_questions(_transcript: str) -> str:
        call_count["n"] += 1
        if call_count["n"] >= 2:
            return OPEN_QUESTIONS_NO_BLOCKING
        return OPEN_QUESTIONS_WITH_BLOCKING

    answers: list[str] = []

    def ask_user(_questions: str) -> str:
        answers.append(f"answer-{len(answers) + 1}")
        return answers[-1]

    text, resolutions = run_bounded_resolution_loop(
        generate_questions=generate_questions, ask_user=ask_user, max_rounds=3
    )
    assert text == OPEN_QUESTIONS_NO_BLOCKING
    assert resolutions == ["answer-1"]


def test_bounded_loop_feeds_the_prior_transcript_back_into_generation() -> None:
    call_count = {"n": 0}
    transcripts_seen: list[str] = []

    def generate_questions(transcript: str) -> str:
        call_count["n"] += 1
        transcripts_seen.append(transcript)
        if call_count["n"] >= 3:
            return OPEN_QUESTIONS_NO_BLOCKING
        return OPEN_QUESTIONS_WITH_BLOCKING

    def ask_user(_questions: str) -> str:
        return "an answer"

    run_bounded_resolution_loop(
        generate_questions=generate_questions, ask_user=ask_user, max_rounds=3
    )

    assert transcripts_seen[0] == ""  # nothing yet on the first round
    assert "an answer" in transcripts_seen[1]  # round 2 sees round 1's Q&A
    assert "an answer" in transcripts_seen[2]


def test_bounded_loop_always_terminates_by_recording_assumptions_on_exhaustion() -> None:
    def generate_questions(_transcript: str) -> str:
        return OPEN_QUESTIONS_WITH_BLOCKING  # always blocking — would loop forever unbounded

    asked: list[str] = []

    def ask_user(_questions: str) -> str:
        asked.append("asked")
        return "an answer"

    text, resolutions = run_bounded_resolution_loop(
        generate_questions=generate_questions, ask_user=ask_user, max_rounds=3
    )
    assert text == OPEN_QUESTIONS_WITH_BLOCKING
    assert len(asked) == 3  # the user gets exactly max_rounds opportunities (T-350)
    assert len(resolutions) == 4  # 3 user answers + 1 documented-assumptions entry
    assert "Assumptions recorded" in resolutions[-1]
    assert "Auth: cookies or JWT?" in resolutions[-1]


def test_bounded_loop_with_max_rounds_one_still_asks_exactly_once() -> None:
    def generate_questions(_transcript: str) -> str:
        return OPEN_QUESTIONS_WITH_BLOCKING

    asked: list[str] = []

    def ask_user(_questions: str) -> str:
        asked.append("asked")
        return "an answer"

    _text, resolutions = run_bounded_resolution_loop(
        generate_questions=generate_questions, ask_user=ask_user, max_rounds=1
    )
    assert len(asked) == 1  # previously: never asked at all (T-350 bug)
    assert len(resolutions) == 2  # 1 user answer + 1 documented-assumptions entry
