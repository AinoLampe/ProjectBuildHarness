"""Test-first: pure ticket-file parsing / build-order logic for Stage 3
(T-210)."""

from pathlib import Path

import pytest

from harness.core.errors import DagCycleError
from harness.stages.implement import (
    diff_changed_paths,
    parse_ticket_file,
    plan_build_order,
    snapshot_tree,
)

TICKET_010 = """# T-010 — Scaffolding

## Connections
- depends on:
- blocks: 020
"""

TICKET_020 = """# T-020 — Core

## Connections
- depends on: 010
- blocks:
"""

CYCLIC_A = "# T-010\n\n## Connections\n- depends on: 020\n"
CYCLIC_B = "# T-020\n\n## Connections\n- depends on: 010\n"


def test_parse_ticket_file_derives_id_from_filename() -> None:
    spec = parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), TICKET_010)
    assert spec.id == "T-010"


def test_parse_ticket_file_extracts_connections() -> None:
    spec = parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), TICKET_010)
    assert spec.blocks == ["T-020"]

    dependent = parse_ticket_file(Path("spec/tickets/020-core.md"), TICKET_020)
    assert dependent.depends_on == ["T-010"]


def test_plan_build_order_respects_dependencies() -> None:
    specs = [
        parse_ticket_file(Path("spec/tickets/020-core.md"), TICKET_020),
        parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), TICKET_010),
    ]
    order = plan_build_order(specs)
    assert order.index("T-010") < order.index("T-020")


def test_plan_build_order_raises_on_cycle() -> None:
    specs = [
        parse_ticket_file(Path("spec/tickets/010-a.md"), CYCLIC_A),
        parse_ticket_file(Path("spec/tickets/020-b.md"), CYCLIC_B),
    ]
    with pytest.raises(DagCycleError):
        plan_build_order(specs)


def test_plan_build_order_handles_empty_list() -> None:
    assert plan_build_order([]) == []


def test_connections_referencing_the_t_prefixed_form_normalise_correctly() -> None:
    # a model writing "depends on: T-010" (not the bare "010") must not
    # become the nonsensical "T-T-010" (T-360).
    text = "# T-020\n\n## Connections\n- depends on: T-010\n"
    spec = parse_ticket_file(Path("spec/tickets/020-core.md"), text)
    assert spec.depends_on == ["T-010"]


def test_connections_referencing_the_overview_are_dropped_not_fatal() -> None:
    text = "# T-010\n\n## Connections\n- depends on: 000\n"
    spec = parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), text)
    assert spec.depends_on == []


def test_parse_ticket_file_extracts_declared_test_scope() -> None:
    text = (
        "# T-010\n\n## Connections\n- depends on:\n\n"
        "### Tests\n- tests/unit/test_dag.py\n- tests/unit/test_folder.py\n"
    )
    spec = parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), text)
    assert spec.test_paths == ["tests/unit/test_dag.py", "tests/unit/test_folder.py"]


def test_parse_ticket_file_with_no_tests_section_has_empty_test_paths() -> None:
    spec = parse_ticket_file(Path("spec/tickets/010-scaffolding.md"), TICKET_010)
    assert spec.test_paths == []


def test_snapshot_tree_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert snapshot_tree(tmp_path / "does-not-exist") == {}


def test_snapshot_tree_and_diff_detect_a_changed_file(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("v1", encoding="utf-8")
    before = snapshot_tree(tmp_path)

    target.write_text("v2 — different length so mtime/size differ", encoding="utf-8")
    after = snapshot_tree(tmp_path)

    changed = diff_changed_paths(before, after)
    assert target in changed


def test_diff_changed_paths_detects_a_new_file(tmp_path: Path) -> None:
    before = snapshot_tree(tmp_path)
    new_file = tmp_path / "new.py"
    new_file.write_text("content", encoding="utf-8")
    after = snapshot_tree(tmp_path)

    assert diff_changed_paths(before, after) == [new_file]


def test_diff_changed_paths_is_empty_when_nothing_changed(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("v1", encoding="utf-8")
    before = snapshot_tree(tmp_path)
    after = snapshot_tree(tmp_path)
    assert diff_changed_paths(before, after) == []
