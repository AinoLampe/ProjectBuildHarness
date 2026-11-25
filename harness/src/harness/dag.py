"""Ticket dependency graph: cycle detection + deterministic topological sort
(concept §9.1, §10.2). Pure logic over structured ticket records — `blocks`
and `depends_on` both contribute ordering edges (`blocks` is just the inverse
declaration of `depends_on`); `relates_to` is non-blocking and ignored for
ordering."""

import heapq
import re
from dataclasses import dataclass, field

from harness.core.errors import DagCycleError, DagReferenceError

_ID_PREFIX_RE = re.compile(r"^T-", re.IGNORECASE)
_ID_NUMBER_RE = re.compile(r"^(\d{3})")


def normalise_ticket_id(raw: str) -> str:
    """Canonicalise a ticket-id reference to its bare 3-digit form: `T-010`,
    `010`, and `010-some-slug` all normalise to `010` (T-360) — so the
    stages that parse Connections (`tickets.py`, `implement.py`) agree on
    one id shape regardless of how a model spells the reference."""
    stripped = _ID_PREFIX_RE.sub("", raw.strip())
    match = _ID_NUMBER_RE.match(stripped)
    if match is None:
        raise DagReferenceError(f"cannot parse a ticket id from {raw!r}")
    return match.group(1)


@dataclass(frozen=True)
class TicketNode:
    id: str
    depends_on: list[str] = field(default_factory=list[str])
    blocks: list[str] = field(default_factory=list[str])
    relates_to: list[str] = field(default_factory=list[str])


def _validate_references(nodes: list[TicketNode], all_ids: set[str]) -> None:
    for node in nodes:
        for ref in (*node.depends_on, *node.blocks):
            if ref not in all_ids:
                raise DagReferenceError(
                    f"ticket {node.id!r} references unknown ticket id {ref!r} in its "
                    "Connections (depends on / blocks)"
                )


def topological_order(nodes: list[TicketNode]) -> list[str]:
    """A stable, deterministic build order in which every dependency
    precedes its dependent. Raises `DagCycleError` naming the cycle if the
    graph is cyclic, or `DagReferenceError` if a node references an id not
    present among `nodes` (T-360) — never a bare `KeyError`."""
    all_ids = {node.id for node in nodes}
    _validate_references(nodes, all_ids)
    successors: dict[str, set[str]] = {node_id: set() for node_id in all_ids}
    in_degree: dict[str, int] = {node_id: 0 for node_id in all_ids}

    def add_edge(prerequisite: str, dependent: str) -> None:
        if dependent not in successors[prerequisite]:
            successors[prerequisite].add(dependent)
            in_degree[dependent] += 1

    for node in nodes:
        for prerequisite in node.depends_on:
            add_edge(prerequisite, node.id)
        for dependent in node.blocks:
            add_edge(node.id, dependent)

    ready = [node_id for node_id, degree in in_degree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[str] = []

    while ready:
        current = heapq.heappop(ready)
        order.append(current)
        for successor in sorted(successors[current]):
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                heapq.heappush(ready, successor)

    if len(order) != len(all_ids):
        remaining = sorted(all_ids - set(order))
        raise DagCycleError(f"ticket dependency graph has a cycle among: {remaining}")

    return order
