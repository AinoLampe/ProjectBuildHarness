"""Test-first: pure consolidation-parsing logic for Stage 1b (T-180, T-500)."""

import json

import pytest

from harness.core.errors import StageError
from harness.stages.guidelines import parse_consolidation

NO_CONFLICT_JSON = json.dumps(
    {
        "conflict_found": False,
        "conflict": "No conflicts found.",
        "resolution": None,
        "revised_concept": None,
    }
)

CONFLICT_WITH_REVISION_JSON = json.dumps(
    {
        "conflict_found": True,
        "conflict": "Guidelines suggested NoSQL; concept implies a relational data model.",
        "resolution": "Relational model wins (concept outranks guidelines).",
        "revised_concept": "# Concept\n\nNow explicitly relational.\n",
    }
)

CONFLICT_NO_REVISION_JSON = json.dumps(
    {
        "conflict_found": True,
        "conflict": "Guidelines suggested a stricter logging format.",
        "resolution": "Adopt the stricter format; it does not contradict the concept.",
        "revised_concept": None,
    }
)


def test_parse_consolidation_no_conflict() -> None:
    outcome = parse_consolidation(NO_CONFLICT_JSON)
    assert outcome.conflict_found is False
    assert outcome.revised_concept is None


def test_the_no_conflicts_found_bug_is_fixed() -> None:
    # historical bug: "No conflicts found." (not the exact phrase "no
    # conflict") was recorded as a *conflict* by keyword matching. The
    # structured contract makes conflict_found a first-class boolean the
    # model sets explicitly, independent of how it phrases `conflict`.
    outcome = parse_consolidation(NO_CONFLICT_JSON)
    assert outcome.conflict_found is False


def test_parse_consolidation_conflict_with_revision() -> None:
    outcome = parse_consolidation(CONFLICT_WITH_REVISION_JSON)
    assert outcome.conflict_found is True
    assert "NoSQL" in (outcome.conflict or "")
    assert "outranks" in (outcome.resolution or "")
    assert outcome.revised_concept is not None
    assert "Now explicitly relational." in outcome.revised_concept


def test_parse_consolidation_conflict_without_revision_leaves_concept_unchanged() -> None:
    outcome = parse_consolidation(CONFLICT_NO_REVISION_JSON)
    assert outcome.conflict_found is True
    assert outcome.revised_concept is None


def test_parse_consolidation_accepts_json_wrapped_in_fencing() -> None:
    text = f"Here's my assessment:\n```json\n{NO_CONFLICT_JSON}\n```\n"
    outcome = parse_consolidation(text)
    assert outcome.conflict_found is False


def test_parse_consolidation_re_asks_once_on_invalid_response() -> None:
    calls: list[str] = []

    def re_ask(prompt: str) -> str:
        calls.append(prompt)
        return NO_CONFLICT_JSON

    outcome = parse_consolidation("not valid json", re_ask=re_ask)
    assert outcome.conflict_found is False
    assert len(calls) == 1


def test_parse_consolidation_raises_after_exhausting_the_re_ask() -> None:
    with pytest.raises(StageError):
        parse_consolidation("not valid json", re_ask=lambda _p: "still not valid")
