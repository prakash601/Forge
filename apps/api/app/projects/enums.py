"""Project-related enums.

Status values match the ``CHECK`` constraint on
``projects.status`` in migration 0004.
"""

from __future__ import annotations

from enum import Enum


class ProjectStatus(str, Enum):
    """Status values for the ``projects.status`` column."""

    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


__all__ = ["ProjectStatus"]
