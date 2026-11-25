"""Behavioural tests for the ticket DAG (T-080, T-360)."""

import pytest

from harness.core.errors import DagCycleError, DagReferenceError
from harness.dag import TicketNode, normalise_ticket_id, topological_order


def test_empty_dag_yields_empty_order() -> None:
    assert topological_order([]) == []


def test_single_node_with_no_edges() -> None:
    assert topological_order([TicketNode(id="T-010")]) == ["T-010"]


def test_depends_on_precedes_its_dependent() -> None:
    nodes = [
        TicketNode(id="T-020", depends_on=["T-010"]),
        TicketNode(id="T-010"),
    ]
    order = topological_order(nodes)
    assert order.index("T-010") < order.index("T-020")


def test_blocks_is_equivalent_to_the_inverse_depends_on() -> None:
    nodes = [
        TicketNode(id="T-010", blocks=["T-020"]),
        TicketNode(id="T-020"),
    ]
    order = topological_order(nodes)
    assert order.index("T-010") < order.index("T-020")


def test_diamond_dependency_graph_respects_all_edges() -> None:
    # T-010 -> {T-020, T-030} -> T-040
    nodes = [
        TicketNode(id="T-010"),
        TicketNode(id="T-020", depends_on=["T-010"]),
        TicketNode(id="T-030", depends_on=["T-010"]),
        TicketNode(id="T-040", depends_on=["T-020", "T-030"]),
    ]
    order = topological_order(nodes)
    assert order.index("T-010") < order.index("T-020")
    assert order.index("T-010") < order.index("T-030")
    assert order.index("T-020") < order.index("T-040")
    assert order.index("T-030") < order.index("T-040")


def test_relates_to_is_non_blocking_and_ignored_for_ordering() -> None:
    nodes = [
        TicketNode(id="T-020", relates_to=["T-099"]),
        TicketNode(id="T-099"),
    ]
    # T-099 is never declared as a dependency or blocker — no ordering constraint,
    # and it must not raise even though T-020 "relates to" an otherwise-unconnected node.
    order = topological_order(nodes)
    assert set(order) == {"T-020", "T-099"}


def test_cyclic_graph_raises_dag_cycle_error_naming_the_cycle() -> None:
    nodes = [
        TicketNode(id="T-010", depends_on=["T-020"]),
        TicketNode(id="T-020", depends_on=["T-010"]),
    ]
    with pytest.raises(DagCycleError) as exc_info:
        topological_order(nodes)
    message = str(exc_info.value)
    assert "T-010" in message
    assert "T-020" in message


def test_self_dependency_is_a_cycle() -> None:
    nodes = [TicketNode(id="T-010", depends_on=["T-010"])]
    with pytest.raises(DagCycleError):
        topological_order(nodes)


def test_ordering_is_deterministic_across_repeated_calls() -> None:
    nodes = [
        TicketNode(id="T-030"),
        TicketNode(id="T-010"),
        TicketNode(id="T-020"),
    ]
    first = topological_order(nodes)
    second = topological_order(list(reversed(nodes)))
    assert first == second == ["T-010", "T-020", "T-030"]


def test_unknown_depends_on_reference_raises_typed_error_naming_both_ids() -> None:
    nodes = [TicketNode(id="T-020", depends_on=["T-010"])]
    with pytest.raises(DagReferenceError) as exc_info:
        topological_order(nodes)
    message = str(exc_info.value)
    assert "T-020" in message
    assert "T-010" in message


def test_unknown_blocks_reference_raises_typed_error() -> None:
    nodes = [TicketNode(id="T-010", blocks=["T-999"])]
    with pytest.raises(DagReferenceError, match="T-999"):
        topological_order(nodes)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("010", "010"),
        ("T-010", "010"),
        ("t-010", "010"),
        ("010-core-primitives", "010"),
        ("T-010-core-primitives", "010"),
        (" T-010 ", "010"),
        ("000", "000"),
    ],
)
def test_normalise_ticket_id_handles_every_spelling(raw: str, expected: str) -> None:
    assert normalise_ticket_id(raw) == expected


def test_normalise_ticket_id_rejects_unparseable_input() -> None:
    with pytest.raises(DagReferenceError):
        normalise_ticket_id("not-a-ticket-id")
