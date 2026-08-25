"""Smoke tests for the shared package placeholder."""

from __future__ import annotations

from forge_shared import __version__


def test_version_is_set() -> None:
    assert isinstance(__version__, str)
    assert __version__
