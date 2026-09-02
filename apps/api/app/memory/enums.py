"""Memory-related enums.

The ``memory_type`` column is intentionally a free-form VARCHAR(100)
in the database; the LLD does not lock the taxonomy. The Python enum
below is the suggested starting set; new types can be added without
a migration as long as the string value fits in the column.
"""

from __future__ import annotations

from enum import Enum


class MemoryType(str, Enum):
    """The kind of fact a memory item records.

    Adding a new member is a non-breaking change for clients; the
    database will accept any ``VARCHAR(100)`` value.
    """

    DECISION = "decision"
    CONVENTION = "convention"
    OBSERVATION = "observation"
    FACT = "fact"
    PREFERENCE = "preference"


class MemoryStatus(str, Enum):
    """Lifecycle status of a memory item.

    Matches the ``CHECK`` constraint in migration 0005.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


__all__ = ["MemoryStatus", "MemoryType"]
