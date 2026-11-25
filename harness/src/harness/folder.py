"""Typed access to the project folder, which *is* the state (concept §3):
canonical paths, safe typed read/write, and the declared-IO guard enforcing
that a stage may only read its declared inputs and write its declared outputs.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any

from harness.core.errors import FolderError


class ProjectFolder:
    """Canonical paths and typed read/write over a single project root."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def requirements_md(self) -> Path:
        return self.root / "requirements.md"

    @property
    def instructions_md(self) -> Path:
        return self.root / "instructions.md"

    @property
    def harness_config_yaml(self) -> Path:
        return self.root / "harness.config.yaml"

    @property
    def spec_dir(self) -> Path:
        return self.root / "spec"

    @property
    def spec_concept_md(self) -> Path:
        return self.spec_dir / "concept.md"

    @property
    def spec_guidelines_md(self) -> Path:
        return self.spec_dir / "guidelines.md"

    @property
    def spec_open_questions_md(self) -> Path:
        return self.spec_dir / "open-questions.md"

    @property
    def spec_phasing_yaml(self) -> Path:
        return self.spec_dir / "phasing.yaml"

    @property
    def spec_tickets_dir(self) -> Path:
        return self.spec_dir / "tickets"

    @property
    def spec_tickets_deferred_dir(self) -> Path:
        """Base directory for tickets written for a not-yet-active phase
        (T-540); tickets for phase `<id>` live under `<this>/<id>/`."""
        return self.spec_tickets_dir / "deferred"

    def spec_tickets_deferred_phase_dir(self, phase_id: str) -> Path:
        return self.spec_tickets_deferred_dir / phase_id

    @property
    def spec_lock_dir(self) -> Path:
        return self.spec_dir / ".lock"

    @property
    def spec_invalidated_dir(self) -> Path:
        return self.spec_dir / ".invalidated"

    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def journal_decisions_md(self) -> Path:
        return self.journal_dir / "DECISIONS.md"

    @property
    def journal_decisions_json(self) -> Path:
        return self.journal_dir / "decisions.json"

    @property
    def journal_progress_md(self) -> Path:
        return self.journal_dir / "PROGRESS.md"

    @property
    def journal_progress_json(self) -> Path:
        return self.journal_dir / "progress.json"

    @property
    def journal_run_log(self) -> Path:
        return self.journal_dir / "run.log"

    @property
    def journal_gates_md(self) -> Path:
        return self.journal_dir / "GATES.md"

    @property
    def journal_gates_json(self) -> Path:
        return self.journal_dir / "gates.json"

    @property
    def journal_escalations_md(self) -> Path:
        return self.journal_dir / "ESCALATIONS.md"

    @property
    def journal_escalations_json(self) -> Path:
        return self.journal_dir / "escalations.json"

    @property
    def src_dir(self) -> Path:
        return self.root / "src"

    def read_text(self, path: Path, *, required: bool = True) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            if required:
                raise FolderError(f"required file is missing or unreadable: {path}") from exc
            return None

    def write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append_text(self, path: Path, content: str) -> None:
        """Append `content` without ever reading the file's existing
        contents — O(1) per call and immune to a crash mid-read corrupting
        the read-modify-write cycle (T-390)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(content)

    def read_json(self, path: Path, *, required: bool = True) -> Any:
        text = self.read_text(path, required=required)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FolderError(f"{path} is not valid JSON: {exc}") from exc

    def write_json(self, path: Path, data: Any) -> None:
        self.write_text(path, json.dumps(data, indent=2))

    def write_json_atomic(self, path: Path, data: Any) -> None:
        """Write `data` to `path` via a same-directory temp file + atomic
        `os.replace`, so a crash mid-write leaves either the old or the new
        content — never a truncated file (T-390)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def declared_io(self, *, inputs: list[Path], outputs: list[Path]) -> "DeclaredIOGuard":
        return DeclaredIOGuard(self, inputs=inputs, outputs=outputs)


class DeclaredIOGuard:
    """Restricts a stage to exactly its declared input/output files.

    Reading anything outside `inputs`, or writing anything outside `outputs`,
    raises `FolderError` — "a stage may only read the input files it declares
    and may only write the output files it declares" (concept §3).
    """

    def __init__(self, folder: ProjectFolder, *, inputs: list[Path], outputs: list[Path]) -> None:
        self._folder = folder
        self._inputs = {p.resolve() for p in inputs}
        self._outputs = {p.resolve() for p in outputs}

    def read_text(self, path: Path, *, required: bool = True) -> str | None:
        if path.resolve() not in self._inputs:
            raise FolderError(f"undeclared read: {path} is not a declared input")
        return self._folder.read_text(path, required=required)

    def read_json(self, path: Path, *, required: bool = True) -> Any:
        if path.resolve() not in self._inputs:
            raise FolderError(f"undeclared read: {path} is not a declared input")
        return self._folder.read_json(path, required=required)

    def write_text(self, path: Path, content: str) -> None:
        if path.resolve() not in self._outputs:
            raise FolderError(f"undeclared write: {path} is not a declared output")
        self._folder.write_text(path, content)

    def write_json(self, path: Path, data: Any) -> None:
        if path.resolve() not in self._outputs:
            raise FolderError(f"undeclared write: {path} is not a declared output")
        self._folder.write_json(path, data)
