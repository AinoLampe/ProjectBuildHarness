"""Fake-adapter driven end-to-end tests for Stage 1b (T-180, T-500)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from harness.adapters.text import GenerationResult, TokenUsage
from harness.core.clock import FrozenClock
from harness.folder import ProjectFolder
from harness.journal import read_decisions
from harness.stages.guidelines import GuidelinesStage
from tests.fakes.fake_text import FakeTextAdapter


def no_conflict_json() -> str:
    return json.dumps(
        {"conflict_found": False, "conflict": None, "resolution": None, "revised_concept": None}
    )


FIXED = datetime(2026, 1, 1, tzinfo=UTC)


def gen(text: str) -> GenerationResult:
    return GenerationResult(text=text, usage=TokenUsage(10, 20))


def test_stage_input_is_concept_only_no_brainstorming_history_reaches_it(
    tmp_path: Path,
) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    folder.write_text(folder.spec_open_questions_md, "brainstorming chatter — must never be seen")
    adapter = FakeTextAdapter(script=[gen("# Guidelines"), gen(no_conflict_json())])
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    for _prompt, files in adapter.calls:
        assert "open-questions.md" not in files
        assert set(files.keys()) <= {"concept.md", "guidelines.md"}


def test_stage_emits_guidelines_and_leaves_concept_untouched_on_no_conflict(
    tmp_path: Path,
) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    adapter = FakeTextAdapter(
        script=[gen("# Guidelines\n\nbest practices"), gen(no_conflict_json())]
    )
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    result = stage.run(folder, adapter, rendered_prompt="")

    assert folder.spec_guidelines_md.read_text(encoding="utf-8") == "# Guidelines\n\nbest practices"
    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept v1"
    assert result.outputs_written == [folder.spec_guidelines_md]
    assert read_decisions(folder) == []


def test_the_no_conflicts_found_prose_no_longer_mismatches_the_bool(tmp_path: Path) -> None:
    # T-500: a model saying "No conflicts found." (not the exact old phrase
    # "no conflict") used to be recorded as a *conflict*. conflict_found is
    # now a first-class boolean the model must set explicitly.
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    consolidation = json.dumps(
        {
            "conflict_found": False,
            "conflict": "No conflicts found.",
            "resolution": None,
            "revised_concept": None,
        }
    )
    adapter = FakeTextAdapter(script=[gen("# Guidelines"), gen(consolidation)])
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    assert read_decisions(folder) == []


def test_conflict_resolves_concept_first_and_logs_to_decisions(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1\n\nNoSQL implied? No, relational.")
    consolidation_json = json.dumps(
        {
            "conflict_found": True,
            "conflict": "Guidelines suggested NoSQL; concept implies relational.",
            "resolution": "Relational wins (concept outranks guidelines).",
            "revised_concept": "# Concept v2\n\nExplicitly relational.\n",
        }
    )
    adapter = FakeTextAdapter(script=[gen("# Guidelines"), gen(consolidation_json)])
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    result = stage.run(folder, adapter, rendered_prompt="")

    decisions = read_decisions(folder)
    assert len(decisions) == 1
    assert "outranks" in decisions[0].resolution
    revised = folder.spec_concept_md.read_text(encoding="utf-8")
    assert revised == "# Concept v2\n\nExplicitly relational.\n"
    assert folder.spec_concept_md in result.outputs_written


def test_conflict_without_revision_leaves_concept_unchanged_but_still_logs(
    tmp_path: Path,
) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    consolidation_json = json.dumps(
        {
            "conflict_found": True,
            "conflict": "Stricter logging format suggested.",
            "resolution": "Adopt it; does not contradict the concept.",
            "revised_concept": None,
        }
    )
    adapter = FakeTextAdapter(script=[gen("# Guidelines"), gen(consolidation_json)])
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept v1"
    assert len(read_decisions(folder)) == 1


def test_unparseable_consolidation_re_asks_once_then_succeeds(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept v1")
    adapter = FakeTextAdapter(
        script=[gen("# Guidelines"), gen("not valid json at all"), gen(no_conflict_json())]
    )
    stage = GuidelinesStage(folder=folder, clock=FrozenClock(FIXED))

    stage.run(folder, adapter, rendered_prompt="")

    assert len(adapter.calls) == 3  # guidelines + failed consolidation + one re-ask
    assert read_decisions(folder) == []
