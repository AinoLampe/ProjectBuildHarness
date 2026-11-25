"""Behavioural tests for project-folder access (T-040)."""

from pathlib import Path

import pytest

from harness.core.errors import FolderError
from harness.folder import ProjectFolder


def test_canonical_paths_resolve_under_root(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert folder.requirements_md == tmp_path / "requirements.md"
    assert folder.instructions_md == tmp_path / "instructions.md"
    assert folder.spec_concept_md == tmp_path / "spec" / "concept.md"
    assert folder.spec_guidelines_md == tmp_path / "spec" / "guidelines.md"
    assert folder.spec_open_questions_md == tmp_path / "spec" / "open-questions.md"
    assert folder.spec_phasing_yaml == tmp_path / "spec" / "phasing.yaml"
    assert folder.spec_tickets_dir == tmp_path / "spec" / "tickets"
    assert folder.spec_lock_dir == tmp_path / "spec" / ".lock"
    assert folder.journal_decisions_md == tmp_path / "journal" / "DECISIONS.md"
    assert folder.journal_decisions_json == tmp_path / "journal" / "decisions.json"
    assert folder.journal_progress_md == tmp_path / "journal" / "PROGRESS.md"
    assert folder.journal_progress_json == tmp_path / "journal" / "progress.json"
    assert folder.journal_run_log == tmp_path / "journal" / "run.log"
    assert folder.src_dir == tmp_path / "src"


def test_reading_missing_required_file_raises_folder_error(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    with pytest.raises(FolderError):
        folder.read_text(folder.requirements_md)


def test_reading_missing_optional_file_returns_none(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert folder.read_text(folder.instructions_md, required=False) is None


def test_write_text_creates_parent_directories(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept\n")
    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept\n"


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "build me a thing")
    assert folder.read_text(folder.requirements_md) == "build me a thing"


def test_json_round_trip(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_json(folder.journal_progress_json, {"a": 1, "b": [1, 2]})
    assert folder.read_json(folder.journal_progress_json) == {"a": 1, "b": [1, 2]}


def test_reading_missing_required_json_raises_folder_error(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    with pytest.raises(FolderError):
        folder.read_json(folder.journal_progress_json)


def test_declared_io_guard_accepts_declared_read_and_write(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.requirements_md, "reqs")
    guard = folder.declared_io(inputs=[folder.requirements_md], outputs=[folder.spec_concept_md])
    assert guard.read_text(folder.requirements_md) == "reqs"
    guard.write_text(folder.spec_concept_md, "# Concept")
    assert folder.spec_concept_md.read_text(encoding="utf-8") == "# Concept"


def test_declared_io_guard_rejects_undeclared_read(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.instructions_md, "extra")
    guard = folder.declared_io(inputs=[folder.requirements_md], outputs=[])
    with pytest.raises(FolderError):
        guard.read_text(folder.instructions_md)


def test_declared_io_guard_rejects_undeclared_write(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    guard = folder.declared_io(inputs=[], outputs=[folder.spec_concept_md])
    with pytest.raises(FolderError):
        guard.write_text(folder.spec_guidelines_md, "nope")


def test_append_text_creates_file_and_parent_dirs(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.append_text(folder.journal_run_log, "line1\n")
    folder.append_text(folder.journal_run_log, "line2\n")
    assert folder.journal_run_log.read_text(encoding="utf-8") == "line1\nline2\n"


def test_append_text_never_reads_existing_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = ProjectFolder(tmp_path)
    folder.append_text(folder.journal_run_log, "line1\n")

    original_read_text = Path.read_text

    def _spy_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == folder.journal_run_log:
            raise AssertionError("append_text must not read the existing file")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _spy_read_text)
    folder.append_text(folder.journal_run_log, "line2\n")
    monkeypatch.undo()
    assert folder.journal_run_log.read_text(encoding="utf-8") == "line1\nline2\n"


def test_write_json_atomic_leaves_prior_content_intact_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_json_atomic(folder.journal_progress_json, {"a": 1})

    def _failing_replace(*args: object, **kwargs: object) -> None:
        raise OSError("simulated crash between temp-write and replace")

    monkeypatch.setattr("os.replace", _failing_replace)
    with pytest.raises(OSError):
        folder.write_json_atomic(folder.journal_progress_json, {"a": 2})

    assert folder.read_json(folder.journal_progress_json) == {"a": 1}
