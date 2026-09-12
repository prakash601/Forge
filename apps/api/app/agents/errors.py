"""Typed errors for the agents package."""

from __future__ import annotations


class ToolPermissionError(PermissionError):
    """A tool call was denied by the agent permission table."""


class ArchaeologistError(RuntimeError):
    """The Archaeologist agent failed (LLM, tools, or persistence)."""


__all__ = [
    "ArchaeologistError",
    "ToolPermissionError",
    "WorkspaceError",
]


class WorkspaceError(RuntimeError):
    """A workspace operation failed (seed, confinement, edit, commit)."""
