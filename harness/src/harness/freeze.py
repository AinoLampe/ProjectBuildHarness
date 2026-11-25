"""Spec freeze + content hashing (concept §8). Snapshots `concept.md` and
`guidelines.md` into an immutable, timestamped, content-hashed
`spec/.lock/<version>/` directory before any code is written, so stages 2/3
build against exactly what the user approved. Re-freezing after an upstream
change produces a new version and invalidates anything built on an older one.
"""

import hashlib
from dataclasses import dataclass

from harness.core.clock import Clock
from harness.core.errors import FolderError
from harness.folder import ProjectFolder

_VERSION_FORMAT = "%Y%m%dT%H%M%SZ"
_MAX_COLLISION_SUFFIXES = 99


@dataclass(frozen=True)
class FrozenSpec:
    version: str
    concept_hash: str
    guidelines_hash: str


@dataclass(frozen=True)
class FrozenSpecContent(FrozenSpec):
    concept_text: str
    guidelines_text: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _next_free_version(folder: ProjectFolder, base_version: str) -> str:
    """`base_version` if free, otherwise `<base_version>-02`, `-03`, ... —
    two freezes within the same clock tick (e.g. an unadvanced `FrozenClock`,
    or a fast re-freeze) must not collide (T-390)."""
    candidate = base_version
    suffix = 2
    while (folder.spec_lock_dir / candidate).exists():
        if suffix > _MAX_COLLISION_SUFFIXES:
            raise FolderError(f"exhausted collision suffixes for frozen version {base_version!r}")
        candidate = f"{base_version}-{suffix:02d}"
        suffix += 1
    return candidate


def freeze_spec(folder: ProjectFolder, clock: Clock) -> FrozenSpec:
    """Snapshot the current `concept.md` + `guidelines.md` into a new,
    immutable `spec/.lock/<version>/` directory. If a freeze already exists
    for this exact clock tick, a distinct suffixed version is used instead of
    overwriting it (T-390) — the frozen spec is immutable, but multiple
    freezes within the same second are not a conflict."""
    concept_text = folder.read_text(folder.spec_concept_md, required=True)
    guidelines_text = folder.read_text(folder.spec_guidelines_md, required=True)
    assert concept_text is not None and guidelines_text is not None  # required=True guarantees

    version = _next_free_version(folder, clock.now().strftime(_VERSION_FORMAT))
    version_dir = folder.spec_lock_dir / version

    folder.write_text(version_dir / "concept.md", concept_text)
    folder.write_text(version_dir / "guidelines.md", guidelines_text)

    concept_hash = _sha256(concept_text)
    guidelines_hash = _sha256(guidelines_text)
    folder.write_json(
        version_dir / "manifest.json",
        {
            "version": version,
            "concept_hash": concept_hash,
            "guidelines_hash": guidelines_hash,
        },
    )
    return FrozenSpec(version=version, concept_hash=concept_hash, guidelines_hash=guidelines_hash)


def read_frozen(folder: ProjectFolder, version: str) -> FrozenSpecContent:
    """Read a previously frozen snapshot by version, verifying its content
    still matches the recorded hash (the frozen spec must never change)."""
    version_dir = folder.spec_lock_dir / version
    manifest = folder.read_json(version_dir / "manifest.json", required=True)
    concept_text = folder.read_text(version_dir / "concept.md", required=True)
    guidelines_text = folder.read_text(version_dir / "guidelines.md", required=True)
    assert concept_text is not None and guidelines_text is not None

    if _sha256(concept_text) != manifest["concept_hash"]:
        raise FolderError(f"frozen concept.md at {version_dir} no longer matches its hash")
    if _sha256(guidelines_text) != manifest["guidelines_hash"]:
        raise FolderError(f"frozen guidelines.md at {version_dir} no longer matches its hash")

    return FrozenSpecContent(
        version=version,
        concept_hash=manifest["concept_hash"],
        guidelines_hash=manifest["guidelines_hash"],
        concept_text=concept_text,
        guidelines_text=guidelines_text,
    )


def latest_version(folder: ProjectFolder) -> str | None:
    """The most recently frozen version, or `None` if nothing has been
    frozen yet. Timestamp version strings sort lexicographically by time."""
    if not folder.spec_lock_dir.exists():
        return None
    versions = sorted(p.name for p in folder.spec_lock_dir.iterdir() if p.is_dir())
    return versions[-1] if versions else None


def is_stale(folder: ProjectFolder, version: str) -> bool:
    """True if `version` is not the latest frozen snapshot — i.e. an
    upstream stage has been re-run and re-frozen since, invalidating
    anything downstream that was built against `version`."""
    return latest_version(folder) != version
