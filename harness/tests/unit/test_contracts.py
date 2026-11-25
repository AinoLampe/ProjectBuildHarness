"""Test-first: structured model-output contracts (T-500)."""

import pytest

from harness.contracts import (
    ConsolidationVerdict,
    OpenQuestions,
    ReadinessSelfCheck,
    TicketSet,
    parse_structured,
)
from harness.core.errors import StageError


def test_parses_bare_json_object() -> None:
    result = parse_structured('{"conflict_found": false}', ConsolidationVerdict)
    assert result.conflict_found is False


def test_the_no_conflicts_found_bug_is_fixed_by_a_first_class_boolean() -> None:
    # the historical bug: "No conflicts found." (not the exact phrase
    # 'no conflict') was recorded as a *conflict* by keyword matching.
    # A structured contract makes this impossible — conflict_found is
    # either true or false, never inferred from prose.
    result = parse_structured(
        '{"conflict_found": false, "conflict": "No conflicts found."}', ConsolidationVerdict
    )
    assert result.conflict_found is False


def test_parses_json_embedded_in_a_fenced_code_block() -> None:
    text = 'Here is my assessment:\n```json\n{"conflict_found": true, '
    text += '"conflict": "x", "resolution": "y"}\n```\nDone.'
    result = parse_structured(text, ConsolidationVerdict)
    assert result.conflict_found is True
    assert result.resolution == "y"


def test_parses_json_embedded_in_bare_fencing_without_json_marker() -> None:
    text = '```\n{"conflict_found": false}\n```'
    result = parse_structured(text, ConsolidationVerdict)
    assert result.conflict_found is False


def test_missing_required_field_triggers_one_re_ask_then_succeeds() -> None:
    re_ask_calls: list[str] = []

    def re_ask(prompt: str) -> str:
        re_ask_calls.append(prompt)
        return '{"conflict_found": true}'  # the corrected response

    result = parse_structured(
        '{"conflict": "oops, forgot the bool"}', ConsolidationVerdict, re_ask=re_ask
    )
    assert result.conflict_found is True
    assert len(re_ask_calls) == 1
    assert "could not be parsed" in re_ask_calls[0]


def test_exhausting_the_single_re_ask_raises_stage_error() -> None:
    def re_ask(_prompt: str) -> str:
        return "still not valid json"

    with pytest.raises(StageError, match="ConsolidationVerdict"):
        parse_structured("not valid json at all", ConsolidationVerdict, re_ask=re_ask)


def test_no_re_ask_given_raises_immediately_on_bad_input() -> None:
    with pytest.raises(StageError):
        parse_structured("not json", ConsolidationVerdict)


def test_readiness_self_check_reports_missing_items() -> None:
    check = ReadinessSelfCheck(
        component_breakdown=True,
        data_model=True,
        external_interfaces=False,
        technology_stack=False,
        data_control_flows=True,
        phasing_decision=True,
    )
    missing = check.missing_items()
    assert "external interfaces and integrations" in missing
    assert "technology stack" in missing
    assert len(missing) == 2


def test_readiness_self_check_all_true_has_no_missing_items() -> None:
    check = ReadinessSelfCheck(
        component_breakdown=True,
        data_model=True,
        external_interfaces=True,
        technology_stack=True,
        data_control_flows=True,
        phasing_decision=True,
    )
    assert check.missing_items() == []


def test_open_questions_parses_severity_tagged_items() -> None:
    text = (
        '{"assumptions": [{"text": "single DB", "severity": "low"}], '
        '"blocking": [{"text": "auth choice", "severity": "high"}], '
        '"suggestions": []}'
    )
    result = parse_structured(text, OpenQuestions)
    assert result.blocking[0].text == "auth choice"
    assert result.blocking[0].severity == "high"


def test_ticket_set_parses_connections() -> None:
    text = (
        '{"tickets": [{"id": "000", "slug": "overview", "body": "Index."}, '
        '{"id": "010", "slug": "core", "body": "Do it.", "phase": "phase-1", '
        '"connections": {"depends_on": ["000"], "blocks": [], "relates_to": []}}]}'
    )
    result = parse_structured(text, TicketSet)
    assert len(result.tickets) == 2
    assert result.tickets[1].connections.depends_on == ["000"]
    assert result.tickets[1].phase == "phase-1"
