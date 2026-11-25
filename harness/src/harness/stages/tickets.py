"""Stage 2 — implementation tickets (concept §9): from the frozen spec,
write the overview/index ticket and one ticket per problem for the active
phase only, validated against the ticket DAG.
"""

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from harness.adapters.text import TextStageAdapter
from harness.core.clock import Clock
from harness.core.errors import DagReferenceError, StageError
from harness.dag import TicketNode, normalise_ticket_id, topological_order
from harness.folder import ProjectFolder
from harness.freeze import is_stale, read_frozen
from harness.journal import DecisionRecord, record_decision
from harness.prompts import DEFAULT_TEMPLATE_VERSION, render_prompt
from harness.stages.base import StageResult, declared_io_for

_TICKET_HEADER_RE = re.compile(
    r"^##\s*TICKET:\s*(\d{3})-([a-z0-9-]+)\s*$", re.IGNORECASE | re.MULTILINE
)
_CONNECTIONS_LINE_RE = re.compile(r"-\s*(depends on|blocks|relates to)\s*:\s*(.*)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedTicket:
    id: str
    slug: str
    body: str
    phase: str | None
    depends_on: list[str] = field(default_factory=list[str])
    blocks: list[str] = field(default_factory=list[str])
    relates_to: list[str] = field(default_factory=list[str])


def _parse_id_list(raw: str) -> list[str]:
    return [normalise_ticket_id(item) for item in raw.split(",") if item.strip()]


def _parse_connections(body: str) -> tuple[list[str], list[str], list[str]]:
    depends_on: list[str] = []
    blocks: list[str] = []
    relates_to: list[str] = []
    for line in body.splitlines():
        match = _CONNECTIONS_LINE_RE.match(line.strip())
        if match is None:
            continue
        kind, ids_text = match.group(1).lower(), match.group(2)
        ids = _parse_id_list(ids_text)
        if kind == "depends on":
            depends_on = ids
        elif kind == "blocks":
            blocks = ids
        elif kind == "relates to":
            relates_to = ids
    return depends_on, blocks, relates_to


def _parse_phase(body: str) -> str | None:
    match = re.search(r"###\s*phase\s*\n(.*?)(?=\n###\s|\Z)", body, re.IGNORECASE | re.DOTALL)
    if match is None:
        return None
    phase = match.group(1).strip()
    return phase or None


def parse_tickets_response(text: str) -> list[ParsedTicket]:
    """Split the model's response into one `ParsedTicket` per `## TICKET:
    NNN-slug` block, extracting its declared phase and Connections."""
    headers = list(_TICKET_HEADER_RE.finditer(text))
    tickets: list[ParsedTicket] = []
    for index, header_match in enumerate(headers):
        start = header_match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[start:end].strip()
        depends_on, blocks, relates_to = _parse_connections(body)
        tickets.append(
            ParsedTicket(
                id=header_match.group(1),
                slug=header_match.group(2),
                body=body,
                phase=_parse_phase(body),
                depends_on=depends_on,
                blocks=blocks,
                relates_to=relates_to,
            )
        )
    return tickets


def _dropped_cross_phase_edges(
    scoped_tickets: list[ParsedTicket], scoped_ids: set[str]
) -> list[str]:
    """Connections referencing a ticket outside `scoped_ids` (a deferred
    phase, or the overview) — dropped from ordering, not fatal (T-360)."""
    dropped: list[str] = []
    for t in scoped_tickets:
        for ref in (*t.depends_on, *t.blocks):
            if ref not in scoped_ids:
                dropped.append(f"{t.id} -> {ref}")
    return dropped


def validate_build_order(
    all_tickets: list[ParsedTicket], scoped_tickets: list[ParsedTicket]
) -> tuple[list[str], list[str]]:
    """Validate every Connections reference across `all_tickets` (T-080's
    `DagReferenceError` catches a genuinely unknown/dangling id — including
    across the overview), then produce the topological build order for
    `scoped_tickets` only. A reference satisfied by a ticket outside the
    scoped set (a deferred phase, or the overview) is a legitimate cross-
    phase dependency, not a cycle or an error: it is dropped from ordering
    and returned as `dropped_edges` for the caller to journal.

    Returns `(build_order, dropped_edges)`."""
    all_ids = {t.id for t in all_tickets}
    for t in all_tickets:
        for ref in (*t.depends_on, *t.blocks):
            if ref not in all_ids:
                raise DagReferenceError(
                    f"ticket {t.id!r} references unknown ticket id {ref!r} — no such "
                    "ticket was produced by this stage"
                )

    scoped_ids = {t.id for t in scoped_tickets if t.id != "000"}
    dropped_edges = _dropped_cross_phase_edges(scoped_tickets, scoped_ids)
    nodes = [
        TicketNode(
            id=t.id,
            depends_on=[d for d in t.depends_on if d in scoped_ids],
            blocks=[b for b in t.blocks if b in scoped_ids],
            relates_to=[],
        )
        for t in scoped_tickets
        if t.id != "000"
    ]
    return topological_order(nodes), dropped_edges


def filter_active_phase(
    tickets: list[ParsedTicket], active_phase: str | None
) -> list[ParsedTicket]:
    """Keep the overview ticket and any ticket whose declared phase matches
    `active_phase` (or has no phase tag at all). Other phases are deferred."""
    if active_phase is None:
        return list(tickets)
    return [t for t in tickets if t.id == "000" or t.phase is None or t.phase == active_phase]


def _active_phase_from_yaml(phasing_yaml_text: str) -> str | None:
    loaded: object = yaml.safe_load(phasing_yaml_text) or {}
    parsed: dict[str, object] = (
        cast("dict[str, object]", loaded) if isinstance(loaded, dict) else {}
    )
    raw_phases: object = parsed.get("phases") or []
    phases = cast("list[object]", raw_phases) if isinstance(raw_phases, list) else []
    for phase in phases:
        if isinstance(phase, dict):
            phase_dict = cast("dict[str, object]", phase)
            if phase_dict.get("active") is True:
                return str(phase_dict.get("id"))
    return None


@dataclass
class TicketsStage:
    folder: ProjectFolder
    frozen_version: str
    clock: Clock
    prompt_version: str = DEFAULT_TEMPLATE_VERSION
    template_dir: Path | None = None
    regeneration_feedback: str | None = None

    @property
    def inputs(self) -> list[Path]:
        version_dir = self.folder.spec_lock_dir / self.frozen_version
        return [
            version_dir / "concept.md",
            version_dir / "guidelines.md",
            self.folder.spec_phasing_yaml,
        ]

    @property
    def outputs(self) -> list[Path]:
        return [
            self.folder.spec_tickets_dir / "000-overview.md",
            self.folder.root / "tickets.zip",
            self.folder.journal_decisions_md,
            self.folder.journal_decisions_json,
        ]

    def run(
        self, folder: ProjectFolder, adapter: TextStageAdapter, rendered_prompt: str
    ) -> StageResult:
        guard = declared_io_for(self, folder)
        if is_stale(folder, self.frozen_version):
            raise StageError(
                f"frozen spec version {self.frozen_version} has been superseded by a later "
                "freeze; re-run against the current frozen version (T-330)"
            )
        frozen = read_frozen(folder, self.frozen_version)
        phasing_text = guard.read_text(self.folder.spec_phasing_yaml) or ""
        active_phase = _active_phase_from_yaml(phasing_text)

        prompt = render_prompt(
            "tickets",
            self.prompt_version,
            {
                "concept": frozen.concept_text,
                "guidelines": frozen.guidelines_text,
                "phasing": phasing_text,
            },
            template_dir=self.template_dir,
        )
        if self.regeneration_feedback is not None:
            prompt += (
                "\n\n## Human feedback from a rejected prior attempt — address it:\n"
                f"{self.regeneration_feedback}"
            )
        response_text = adapter.generate(
            prompt,
            {
                "concept.md": frozen.concept_text,
                "guidelines.md": frozen.guidelines_text,
                "phasing.yaml": phasing_text,
            },
            template_name="tickets",
            template_version=self.prompt_version,
        ).text

        all_tickets = parse_tickets_response(response_text)
        if not all_tickets or all_tickets[0].id != "000":
            raise StageError("the overview ticket (000-overview) must be the first ticket written")

        scoped_tickets = filter_active_phase(all_tickets, active_phase)
        _order, dropped_edges = validate_build_order(all_tickets, scoped_tickets)

        scoped_ids = {t.id for t in scoped_tickets}
        deferred_tickets = [t for t in all_tickets if t.id not in scoped_ids]

        written: list[Path] = []
        for ticket in scoped_tickets:
            filename = "000-overview.md" if ticket.id == "000" else f"{ticket.id}-{ticket.slug}.md"
            path = folder.spec_tickets_dir / filename
            if not path.resolve().is_relative_to(folder.spec_tickets_dir.resolve()):
                raise StageError(f"refusing to write ticket file outside spec/tickets/: {path}")
            folder.write_text(path, ticket.body + "\n")
            written.append(path)

        # T-540: a deferred-phase ticket is archived, not discarded, so
        # `harness phase --next` can promote it later without re-generating
        # Stage 2 output.
        deferred_written: list[Path] = []
        for ticket in deferred_tickets:
            phase_dir = folder.spec_tickets_deferred_phase_dir(ticket.phase or "unphased")
            path = phase_dir / f"{ticket.id}-{ticket.slug}.md"
            if not path.resolve().is_relative_to(folder.spec_tickets_deferred_dir.resolve()):
                raise StageError(
                    f"refusing to write deferred ticket file outside {phase_dir}: {path}"
                )
            folder.write_text(path, ticket.body + "\n")
            deferred_written.append(path)

        zip_path = folder.root / "tickets.zip"
        with zipfile.ZipFile(zip_path, "w") as archive:
            for path in written:
                archive.write(path, arcname=path.name)

        outputs_written = [*written, *deferred_written, zip_path]
        if dropped_edges:
            record_decision(
                folder,
                DecisionRecord(
                    timestamp=self.clock.now(),
                    ticket=None,
                    conflict=(
                        "active-phase tickets reference tickets outside the active phase: "
                        + ", ".join(dropped_edges)
                    ),
                    resolution=(
                        "cross-phase edges dropped from this phase's build order (satisfied by "
                        "a deferred phase or the overview, not a same-phase ordering constraint)"
                    ),
                    reasoning=(
                        "concept §9.4: only active-phase tickets are implemented now; a "
                        "dependency on a later/earlier phase's ticket is not a cycle or an "
                        "error, just outside this phase's scope"
                    ),
                ),
            )
            outputs_written += [folder.journal_decisions_md, folder.journal_decisions_json]

        return StageResult(outputs_written=outputs_written)
