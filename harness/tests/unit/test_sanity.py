"""Sanity check that the package imports and the toolchain runs."""

import harness


def test_package_imports() -> None:
    assert harness.__name__ == "harness"
