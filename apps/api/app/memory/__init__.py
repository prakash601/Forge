"""Memory package.

Project memory is the durable record of what Forge has learned about
a project: decisions, conventions, observations, facts. Each
:class:`MemoryItem` may have at most one :class:`MemoryEmbedding`
(one-to-one via the unique constraint).

This issue implements only the schema and CRUD. Embedding generation
(choosing a model, calling a provider, ingesting pipeline) belongs
to a separate issue. The embedding column is ``VECTOR(1536)`` per
DATABASE_DESIGN §20; that dimension is a placeholder until the model
is locked in.

Layering
--------
``enums``     — :class:`MemoryType`, :class:`MemoryStatus`.
``models``    — SQLAlchemy ORM mapping.
``errors``    — Typed exceptions.
``service``   — Repository-style functions.
``schemas``   — Pydantic request/response shapes.
"""

from __future__ import annotations

from app.memory.enums import MemoryStatus, MemoryType
from app.memory.errors import MemoryItemNotFoundError
from app.memory.models import MemoryEmbedding, MemoryItem
from app.memory.service import (
    create_memory_item,
    get_memory_item,
    list_memory_items_for_project,
)

__all__ = [
    "MemoryEmbedding",
    "MemoryItem",
    "MemoryItemNotFoundError",
    "MemoryStatus",
    "MemoryType",
    "create_memory_item",
    "get_memory_item",
    "list_memory_items_for_project",
]
