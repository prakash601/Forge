"""Shared SQLAlchemy declarative base.

All package-level ``Base`` classes (``app.users.models.Base``,
``app.projects.models.Base``, ``app.memory.models.Base``,
``app.runs.models.Base``) historically inherited directly from
:class:`sqlalchemy.orm.DeclarativeBase`. This broke cross-package
foreign keys because each Base has its own metadata, so a
``ForeignKey("users.id")`` declared on a Project model whose Base
did not also define the User model would fail at class-creation
time with ``NoReferencedTableError``.

The single shared :class:`Base` below is the fix: every model in
the application now inherits from this Base, so all tables live
in a single ``MetaData`` and FK references resolve correctly.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The application's single declarative base.

    All ORM models in ``app.*.models`` inherit from this class. New
    packages should follow the same convention.
    """


__all__ = ["Base"]
