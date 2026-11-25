"""Behavioural tests for the prompt template loader + renderer (T-090)."""

from pathlib import Path

import pytest

from harness.core.errors import PromptError
from harness.prompts import (
    DEFAULT_TEMPLATE_DIR,
    DEFAULT_TEMPLATE_VERSION,
    NAMED_TEMPLATES,
    render_prompt,
)


@pytest.mark.parametrize("name", NAMED_TEMPLATES)
def test_every_named_default_template_exists(name: str) -> None:
    path = DEFAULT_TEMPLATE_DIR / DEFAULT_TEMPLATE_VERSION / f"{name}.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip() != ""


def test_render_substitutes_provided_variables(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "greeting.md").write_text("Hello {{name}}, today is {{day}}.", encoding="utf-8")

    rendered = render_prompt(
        "greeting", "v1", variables={"name": "Ada", "day": "Tuesday"}, template_dir=tmp_path
    )
    assert rendered == "Hello Ada, today is Tuesday."


def test_missing_template_raises_prompt_error(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        render_prompt("does-not-exist", "v1", variables={}, template_dir=tmp_path)


def test_missing_variable_raises_prompt_error_no_silent_blank(tmp_path: Path) -> None:
    version_dir = tmp_path / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "greeting.md").write_text("Hello {{name}}.", encoding="utf-8")

    with pytest.raises(PromptError, match="name"):
        render_prompt("greeting", "v1", variables={}, template_dir=tmp_path)


def test_project_template_dir_overrides_shipped_default(tmp_path: Path) -> None:
    version_dir = tmp_path / DEFAULT_TEMPLATE_VERSION
    version_dir.mkdir(parents=True)
    (version_dir / "brainstorm.md").write_text("custom override content", encoding="utf-8")

    rendered = render_prompt(
        "brainstorm", DEFAULT_TEMPLATE_VERSION, variables={}, template_dir=tmp_path
    )
    assert rendered == "custom override content"


def test_unconfigured_version_falls_back_to_missing_template_error(tmp_path: Path) -> None:
    with pytest.raises(PromptError):
        render_prompt("brainstorm", "v999-does-not-exist", variables={}, template_dir=None)
