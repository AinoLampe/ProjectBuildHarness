"""Injected determinism seam for identifier generation. Real code uses
`UuidGen`; tests use `SeqIdGen` for a deterministic, monotonic sequence."""

import uuid
from typing import Protocol


class IdGen(Protocol):
    """Anything that can mint a new unique identifier."""

    def next_id(self) -> str: ...


class UuidGen:
    """Real id generator backed by `uuid4`."""

    def next_id(self) -> str:
        return str(uuid.uuid4())


class SeqIdGen:
    """Deterministic, monotonic id generator: `<prefix>-0001`, `-0002`, ..."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._counter = 0

    def next_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:04d}"
