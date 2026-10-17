"""Typed exceptions for the projects service."""

from __future__ import annotations


class ProjectNotFoundError(LookupError):
    """No Project exists with the given identifier."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Project {self.project_id!r} does not exist."


class DuplicateProjectNameError(ValueError):
    """A project with the same name already exists for this owner.

    (Optional uniqueness — currently we do NOT enforce a per-owner
    unique name. This error is reserved for a future migration that
    adds a UNIQUE (owner_id, name) constraint.)
    """

    def __init__(self, owner_id: str, name: str) -> None:
        super().__init__(owner_id, name)
        self.owner_id = owner_id
        self.name = name

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"A project named {self.name!r} already exists for owner {self.owner_id!r}."


__all__ = ["DuplicateProjectNameError", "ProjectNotFoundError"]
