"""Versioned prompt template loader + renderer (concept §15). Every injected
prompt is a template file under `(template_dir or DEFAULT_TEMPLATE_DIR)
/<version>/<name>.md`, rendered with `{{variable}}` substitution — never a
hard-coded string — so prompts can be improved and versioned without code
changes. A project-level `template_dir` overrides the shipped defaults.
"""

import re
from pathlib import Path

from harness.core.errors import PromptError

DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "prompt_templates"
DEFAULT_TEMPLATE_VERSION = "v1"

NAMED_TEMPLATES = (
    "brainstorm",
    "concept_write",
    "concept_self_review",
    "guidelines",
    "guidelines_consolidation",
    "tickets",
    "implement_bootstrap",
    "review_gate",
    "final_acceptance",
    "implement_retry",
    "concept_revise",
)

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def _resolve_template_path(name: str, version: str, template_dir: Path | None) -> Path:
    search_dirs: list[Path] = []
    if template_dir is not None:
        search_dirs.append(template_dir / version)
    search_dirs.append(DEFAULT_TEMPLATE_DIR / version)

    for directory in search_dirs:
        candidate = directory / f"{name}.md"
        if candidate.is_file():
            return candidate

    raise PromptError(f"no template named {name!r} at version {version!r} (searched {search_dirs})")


def extract_placeholders(text: str) -> set[str]:
    """The set of `{{variable}}` names referenced in `text` (T-550) — used
    to assert a template's placeholders exactly match what its stage
    supplies, catching drift in either direction."""
    return set(_PLACEHOLDER.findall(text))


def render_prompt(
    name: str, version: str, variables: dict[str, str], template_dir: Path | None = None
) -> str:
    """Load template `name`/`version` (project override first, then the
    shipped default) and substitute `{{variable}}` placeholders. Raises
    `PromptError` if the template is missing or a placeholder has no
    matching variable (no silent blanks)."""
    path = _resolve_template_path(name, version, template_dir)
    text = path.read_text(encoding="utf-8")

    placeholders = set(_PLACEHOLDER.findall(text))
    missing = placeholders - variables.keys()
    if missing:
        raise PromptError(
            f"template {name!r} is missing variable(s) {sorted(missing)} for rendering"
        )

    return _PLACEHOLDER.sub(lambda m: str(variables[m.group(1)]), text)
