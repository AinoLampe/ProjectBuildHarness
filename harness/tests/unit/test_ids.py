"""Behavioural tests for the IdGen seam (T-020)."""

import uuid

from harness.core.ids import IdGen, SeqIdGen, UuidGen


def test_uuid_gen_produces_distinct_parseable_uuids() -> None:
    gen: IdGen = UuidGen()
    first = gen.next_id()
    second = gen.next_id()
    assert first != second
    uuid.UUID(first)
    uuid.UUID(second)


def test_seq_id_gen_is_deterministic_and_monotonic() -> None:
    gen: IdGen = SeqIdGen(prefix="id")
    assert gen.next_id() == "id-0001"
    assert gen.next_id() == "id-0002"
    assert gen.next_id() == "id-0003"


def test_seq_id_gen_two_instances_are_independent() -> None:
    a = SeqIdGen(prefix="a")
    b = SeqIdGen(prefix="a")
    assert a.next_id() == "a-0001"
    assert b.next_id() == "a-0001"
