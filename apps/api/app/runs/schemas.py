"""Pydantic schemas for the Run state machine API.

Request/response shapes follow ``docs/api/OPENAPI_v0.1.md`` (error envelope
contract) and ``docs/design/STATE_MACHINE_v0.1.md`` (state/event names).

We expose the full Run representation on create + read so callers can
introspect the timeline (``steps``). The state machine is a public
contract; serialising it does not leak implementation details.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.runs.enums import RunEvent, RunState


class RunStepRead(BaseModel):
    """One applied event in a Run's history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    from_state: RunState
    event: str
    to_state: RunState
    created_at: datetime


class RunRead(BaseModel):
    """Full Run view returned by ``GET /runs/{id}`` and create responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    state: RunState
    is_terminal: bool
    task: str
    version: int
    created_at: datetime
    updated_at: datetime
    steps: list[RunStepRead] = Field(default_factory=list)


class RunCreateRequest(BaseModel):
    """Body for ``POST /runs``."""

    task: str = Field(
        min_length=1,
        max_length=10_000,
        description="Free-form description of the engineering task.",
    )


class RunEventRequest(BaseModel):
    """Body for ``POST /runs/{id}/events``.

    ``event`` is intentionally typed as ``str`` rather than ``RunEvent``
    so that unknown event names produce a clean 422 with code
    ``VALIDATION_ERROR`` — a malformed payload — instead of an opaque
    500 from the enum parser. The service layer raises
    :class:`UnknownEventError` only when an event value bypasses this
    schema (which should not happen in practice; this is defence in
    depth).
    """

    event: str = Field(
        min_length=1,
        max_length=128,
        description="Event name. See RunEvent in app.runs.enums.",
    )


# Events that the v1 API accepts. Kept as a literal list so we can render
# a useful 422 message when the caller sends an event that the enum does
# not know about.
ACCEPTED_EVENTS: tuple[str, ...] = tuple(member.value for member in RunEvent)


def event_choices() -> list[dict[str, Any]]:
    """Return ``[{value, description}, ...]`` for OpenAPI schema generation."""
    return [{"value": e.value, "description": e.name} for e in RunEvent]


__all__ = [
    "ACCEPTED_EVENTS",
    "RunCreateRequest",
    "RunEventRequest",
    "RunRead",
    "RunStepRead",
    "event_choices",
]
