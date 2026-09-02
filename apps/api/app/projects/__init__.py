"""Projects package.

A Project groups Runs and Memory Items under a single owner. This
package implements the full project CRUD per the LLD and the project
status enum per DATABASE_DESIGN_v0.1.md §8.

Layering
--------
``enums``    — :class:`ProjectStatus`.
``models``   — SQLAlchemy ORM mapping.
``errors``   — Typed exceptions.
``service``  — Repository-style functions.
``schemas``  — Pydantic request/response shapes.
"""

from __future__ import annotations

from app.projects.enums import ProjectStatus
from app.projects.errors import DuplicateProjectNameError, ProjectNotFoundError
from app.projects.models import Project
from app.projects.service import (
    create_project,
    get_project,
    list_projects_for_owner,
)

__all__ = [
    "DuplicateProjectNameError",
    "Project",
    "ProjectNotFoundError",
    "ProjectStatus",
    "create_project",
    "get_project",
    "list_projects_for_owner",
]
