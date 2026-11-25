"""Structured, pydantic-validated model-output contracts (T-500).

Several stages used to scrape free-form prose with regexes/keyword
matching — brittle by construction: a model answering "No conflicts
found." (not the exact phrase `"no conflict"`) was recorded as a
**conflict** by `guidelines.py`'s old `_NO_CONFLICT_PHRASES` check, and a
concept mentioning the word "phase" anywhere passed `concept.py`'s old
keyword-sniffed readiness check. This module replaces that pattern: every
prompt that feeds a *parser* demands a machine-validatable JSON object,
validated here against a pydantic model, with exactly one bounded re-ask
on failure before giving up loudly.
"""

import json
import re
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

from harness.core.errors import StageError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


class QuestionItem(BaseModel):
    text: str
    severity: str = "med"


class OpenQuestions(BaseModel):
    """Structured form of Stage 1a's brainstorm output (concept §6.1)."""

    assumptions: list[QuestionItem] = []
    blocking: list[QuestionItem] = []
    suggestions: list[QuestionItem] = []


class ReadinessSelfCheck(BaseModel):
    """The model's own structured assessment against the concept §6.4
    readiness checklist — replaces keyword-sniffing the rendered concept
    text for phrases like "tech stack"."""

    component_breakdown: bool
    data_model: bool
    external_interfaces: bool
    technology_stack: bool
    data_control_flows: bool
    phasing_decision: bool

    def missing_items(self) -> list[str]:
        labels = {
            "component_breakdown": "component breakdown and responsibilities",
            "data_model": "data model / key entities",
            "external_interfaces": "external interfaces and integrations",
            "technology_stack": "technology stack",
            "data_control_flows": "major data and control flows",
            "phasing_decision": "phasing decision",
        }
        return [label for field, label in labels.items() if not getattr(self, field)]


class ConsolidationVerdict(BaseModel):
    """Stage 1b's concept/guidelines consolidation check (concept §7).
    `conflict_found` is a first-class boolean — no more matching the
    conflict-description text against a fixed phrase list."""

    conflict_found: bool
    conflict: str | None = None
    resolution: str | None = None
    revised_concept: str | None = None


class TicketConnections(BaseModel):
    depends_on: list[str] = []
    blocks: list[str] = []
    relates_to: list[str] = []


class TicketItem(BaseModel):
    id: str
    slug: str
    body: str
    phase: str | None = None
    connections: TicketConnections = TicketConnections()


class TicketSet(BaseModel):
    """Stage 2's ticket batch (concept §9) — the overview is `tickets[0]`."""

    tickets: list[TicketItem]


def _extract_json_candidates(text: str) -> list[str]:
    """Candidates to try, in order: the whole text verbatim, then each
    fenced ```json block found within it (a model often wraps its answer
    in prose or markdown fencing despite being asked for JSON only)."""
    candidates = [text.strip()]
    candidates.extend(match.group(1).strip() for match in _JSON_FENCE_RE.finditer(text))
    return candidates


def _try_parse[T: BaseModel](text: str, model_cls: type[T]) -> tuple[T | None, str | None]:
    last_error: str | None = None
    for candidate in _extract_json_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            continue
        try:
            return model_cls.model_validate(data), None
        except ValidationError as exc:
            last_error = str(exc)
    return None, last_error


def parse_structured[T: BaseModel](
    text: str, model_cls: type[T], *, re_ask: Callable[[str], str] | None = None
) -> T:
    """Parse and validate `text` against `model_cls`. If nothing in `text`
    validates and `re_ask` is given, ask once more (with the validation
    error appended) before raising `StageError` — one bounded retry, never
    an unbounded loop."""
    parsed, error = _try_parse(text, model_cls)
    if parsed is not None:
        return parsed

    if re_ask is not None:
        retry_text = re_ask(
            f"{text}\n\nYour previous response could not be parsed as valid "
            f"{model_cls.__name__} JSON ({error}). Respond again with exactly one JSON "
            "object matching the required schema — no prose, no fencing."
        )
        parsed, error = _try_parse(retry_text, model_cls)
        if parsed is not None:
            return parsed

    raise StageError(
        f"could not parse a valid {model_cls.__name__} from the model's response: {error}"
    )
