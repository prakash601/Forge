"""User-related enums.

The MVP defines a single status placeholder. A later issue extends this
with auth-related states (e.g. ``PENDING_VERIFICATION``).
"""

from __future__ import annotations

from enum import Enum


class UserStatus(str, Enum):
    """Status values for the ``users.status`` column.

    Currently the database does not have a ``status`` column on
    ``users`` (the LLD does not require it for Issue #003). This
    enum is defined ahead of need so future issues can adopt it
    without a code rewrite.
    """

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


__all__ = ["UserStatus"]
