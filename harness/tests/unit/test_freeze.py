"""Behavioural tests for spec freeze + content hashing (T-070)."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness.core.clock import FrozenClock
from harness.core.errors import FolderError
from harness.folder import ProjectFolder
from harness.freeze import freeze_spec, is_stale, latest_version, read_frozen


def seed_spec(
    folder: ProjectFolder, *, concept: str = "# Concept v1", guidelines: str = "# G v1"
) -> None:
    folder.write_text(folder.spec_concept_md, concept)
    folder.write_text(folder.spec_guidelines_md, guidelines)


def test_freeze_creates_timestamped_lock_dir_with_copies_and_hashes(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    seed_spec(folder)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))

    frozen = freeze_spec(folder, clock)

    version_dir = folder.spec_lock_dir / frozen.version
    assert (version_dir / "concept.md").read_text(encoding="utf-8") == "# Concept v1"
    assert (version_dir / "guidelines.md").read_text(encoding="utf-8") == "# G v1"
    assert frozen.concept_hash == hashlib.sha256(b"# Concept v1").hexdigest()
    assert frozen.guidelines_hash == hashlib.sha256(b"# G v1").hexdigest()


def test_freeze_requires_both_source_files_present(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    folder.write_text(folder.spec_concept_md, "# Concept only")
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    with pytest.raises(FolderError):
        freeze_spec(folder, clock)


def test_frozen_snapshot_is_immutable_even_if_source_changes_later(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    seed_spec(folder)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    frozen = freeze_spec(folder, clock)

    folder.write_text(folder.spec_concept_md, "# Concept v2 — changed after freeze")

    read_back = read_frozen(folder, frozen.version)
    assert read_back.concept_text == "# Concept v1"
    assert read_back.concept_hash == frozen.concept_hash


def test_refreezing_at_the_same_instant_yields_a_distinct_suffixed_version(
    tmp_path: Path,
) -> None:
    folder = ProjectFolder(tmp_path)
    seed_spec(folder)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    first = freeze_spec(folder, clock)
    folder.write_text(folder.spec_concept_md, "# Concept v2 (still same instant)")
    second = freeze_spec(folder, clock)  # same timestamp as `first`

    assert second.version != first.version
    assert second.version.startswith(first.version)
    assert latest_version(folder) == second.version
    # both remain independently readable — neither was overwritten
    assert read_frozen(folder, first.version).concept_text == "# Concept v1"
    assert read_frozen(folder, second.version).concept_text == "# Concept v2 (still same instant)"


def test_three_freezes_at_the_same_instant_all_get_distinct_versions(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    seed_spec(folder)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    versions = [freeze_spec(folder, clock).version for _ in range(3)]
    assert len(set(versions)) == 3
    assert latest_version(folder) == sorted(versions)[-1] == versions[-1]


def test_refreezing_after_upstream_change_yields_a_new_version_and_invalidates_downstream(
    tmp_path: Path,
) -> None:
    folder = ProjectFolder(tmp_path)
    seed_spec(folder)
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))
    first = freeze_spec(folder, clock)

    assert is_stale(folder, first.version) is False  # it is the latest, not stale yet

    clock.advance(timedelta(minutes=5))
    folder.write_text(folder.spec_concept_md, "# Concept v2")
    second = freeze_spec(folder, clock)

    assert second.version != first.version
    assert latest_version(folder) == second.version
    assert is_stale(folder, first.version) is True  # downstream built on `first` is now invalid
    assert is_stale(folder, second.version) is False


def test_latest_version_is_none_when_nothing_has_been_frozen(tmp_path: Path) -> None:
    folder = ProjectFolder(tmp_path)
    assert latest_version(folder) is None
