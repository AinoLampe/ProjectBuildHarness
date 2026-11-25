"""Test-first: pure parsing/validation logic for Stage 2 (T-190)."""

import pytest

from harness.core.errors import DagCycleError, DagReferenceError
from harness.stages.tickets import (
    filter_active_phase,
    parse_tickets_response,
    validate_build_order,
)

SAMPLE_RESPONSE = """
## TICKET: 000-overview
### Goal
Index ticket.

## TICKET: 010-scaffolding
### Goal
Stand up the repo.

### Connections
- depends on:
- blocks: 020
- relates to:

## TICKET: 020-core
### Goal
Core primitives.

### Connections
- depends on: 010
- blocks:
- relates to:
"""

PHASED_RESPONSE = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-phase-one-thing
### Phase
phase-1

### Connections
- depends on:

## TICKET: 020-phase-two-thing
### Phase
phase-2

### Connections
- depends on:
"""

CYCLIC_RESPONSE = """
## TICKET: 010-a
### Connections
- depends on: 020

## TICKET: 020-b
### Connections
- depends on: 010
"""


def test_parse_tickets_response_extracts_each_ticket_block() -> None:
    tickets = parse_tickets_response(SAMPLE_RESPONSE)
    ids = [t.id for t in tickets]
    assert ids == ["000", "010", "020"]


def test_parse_tickets_response_extracts_connections() -> None:
    tickets = {t.id: t for t in parse_tickets_response(SAMPLE_RESPONSE)}
    assert tickets["010"].blocks == ["020"]
    assert tickets["020"].depends_on == ["010"]


def test_parse_tickets_response_defaults_phase_to_none() -> None:
    tickets = {t.id: t for t in parse_tickets_response(SAMPLE_RESPONSE)}
    assert tickets["010"].phase is None


def test_parse_tickets_response_extracts_declared_phase() -> None:
    tickets = {t.id: t for t in parse_tickets_response(PHASED_RESPONSE)}
    assert tickets["010"].phase == "phase-1"
    assert tickets["020"].phase == "phase-2"


def test_validate_build_order_excludes_overview_and_orders_dependencies() -> None:
    tickets = parse_tickets_response(SAMPLE_RESPONSE)
    order, dropped = validate_build_order(tickets, tickets)
    assert order.index("010") < order.index("020")
    assert "000" not in order
    assert dropped == []


def test_validate_build_order_raises_on_cycle() -> None:
    tickets = parse_tickets_response(CYCLIC_RESPONSE)
    with pytest.raises(DagCycleError):
        validate_build_order(tickets, tickets)


def test_validate_build_order_raises_typed_error_on_unknown_reference() -> None:
    response = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-a
### Connections
- depends on: 999
"""
    tickets = parse_tickets_response(response)
    with pytest.raises(DagReferenceError, match="999"):
        validate_build_order(tickets, tickets)


def test_validate_build_order_normalises_connection_id_spellings() -> None:
    response = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-a
### Goal
A.

## TICKET: 020-b
### Connections
- depends on: T-010
"""
    tickets = parse_tickets_response(response)
    order, dropped = validate_build_order(tickets, tickets)
    assert order.index("010") < order.index("020")
    assert dropped == []


def test_validate_build_order_drops_cross_phase_dependency_without_erroring() -> None:
    # 010 (active phase) depends on 020 (a deferred phase) — a legitimate
    # cross-phase edge, not a cycle or an unknown reference (T-360).
    response = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-active
### Phase
phase-1

### Connections
- depends on: 020

## TICKET: 020-deferred
### Phase
phase-2
"""
    all_tickets = parse_tickets_response(response)
    scoped = [t for t in all_tickets if t.id != "020"]  # 020 filtered out by active-phase scoping
    order, dropped = validate_build_order(all_tickets, scoped)
    assert order == ["010"]
    assert dropped == ["010 -> 020"]


def test_validate_build_order_ignores_overview_reference() -> None:
    response = """
## TICKET: 000-overview
### Goal
Index.

## TICKET: 010-a
### Connections
- depends on: 000
"""
    tickets = parse_tickets_response(response)
    order, dropped = validate_build_order(tickets, tickets)
    assert order == ["010"]
    assert dropped == ["010 -> 000"]


def test_filter_active_phase_keeps_overview_and_matching_phase_only() -> None:
    tickets = parse_tickets_response(PHASED_RESPONSE)
    kept = filter_active_phase(tickets, active_phase="phase-1")
    kept_ids = [t.id for t in kept]
    assert "000" in kept_ids
    assert "010" in kept_ids
    assert "020" not in kept_ids


def test_filter_active_phase_keeps_everything_when_no_phasing_declared() -> None:
    tickets = parse_tickets_response(SAMPLE_RESPONSE)  # no phase tags at all
    kept = filter_active_phase(tickets, active_phase=None)
    assert len(kept) == len(tickets)
