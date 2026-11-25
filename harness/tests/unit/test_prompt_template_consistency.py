"""T-550: every shipped template's placeholders must exactly match the
variables the corresponding stage actually supplies at render time — this
catches drift in either direction (an unused variable in the code, or a
placeholder the code never supplies, which would raise `PromptError` at
run time against a real model)."""

import pytest

from harness.prompts import DEFAULT_TEMPLATE_DIR, DEFAULT_TEMPLATE_VERSION, extract_placeholders

# One entry per named template: the exact variable set its stage passes to
# `render_prompt`/`self._render` today. Update this alongside any stage
# change that adds/removes a variable.
EXPECTED_VARIABLES: dict[str, set[str]] = {
    "brainstorm": {"requirements", "instructions", "qa_transcript"},
    "concept_write": {"requirements", "resolved_questions"},
    "concept_self_review": {"concept", "qa_transcript"},
    "concept_revise": {"concept", "resolutions"},
    "guidelines": {"concept"},
    "guidelines_consolidation": {"concept", "guidelines"},
    "tickets": {"concept", "guidelines", "phasing"},
    "implement_bootstrap": {
        "ticket_id",
        "ticket_text",
        "frozen_concept_path",
        "frozen_guidelines_path",
        "overview_path",
        "journal_dir",
    },
    "review_gate": {
        "ticket_text",
        "acceptance_criteria",
        "changed_files",
        "objective_results",
        "concept_path",
        "guidelines_path",
    },
    "final_acceptance": {"requirements", "frozen_concept"},
    "implement_retry": {"original_prompt", "reasons"},
}


def test_every_named_template_has_an_expected_variable_entry() -> None:
    from harness.prompts import NAMED_TEMPLATES

    assert set(NAMED_TEMPLATES) == set(EXPECTED_VARIABLES)


@pytest.mark.parametrize("name", sorted(EXPECTED_VARIABLES))
def test_template_placeholders_exactly_match_supplied_variables(name: str) -> None:
    path = DEFAULT_TEMPLATE_DIR / DEFAULT_TEMPLATE_VERSION / f"{name}.md"
    placeholders = extract_placeholders(path.read_text(encoding="utf-8"))
    assert placeholders == EXPECTED_VARIABLES[name], (
        f"{name}.md placeholders {placeholders} != supplied variables {EXPECTED_VARIABLES[name]}"
    )


def test_no_shipped_template_contains_the_first_draft_placeholder_marker() -> None:
    template_dir = DEFAULT_TEMPLATE_DIR / DEFAULT_TEMPLATE_VERSION
    offenders = [
        path.name
        for path in template_dir.glob("*.md")
        if "FIRST-DRAFT PLACEHOLDER" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
