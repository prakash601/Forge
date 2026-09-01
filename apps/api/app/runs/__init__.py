"""Run state machine package.

This package implements the durable Run state machine described in
``docs/design/STATE_MACHINE_v0.1.md``. The state machine is the *only*
authority on which state transitions are valid; the application code calls
into :func:`app.runs.service.transition` and trusts the result.

Layering
--------
``enums``     — pure Python values. The state and event names are the
                canonical contract; both the database enum and the
                transition table reference these names verbatim.
``transitions`` — declarative transition table mirroring STATE_MACHINE §4.
                No I/O, no database. Easy to unit-test exhaustively.
``models``    — SQLAlchemy ORM mapping for the ``runs`` and ``run_steps``
                tables introduced in migration ``0002_runs_and_run_steps``.
``errors``    — Typed exceptions raised by the service layer. Translated
                to HTTP error envelopes at the API boundary.
``service``   — ``transition(run_id, event) -> Run``. Single chokepoint
                that validates against the transition table and persists
                the new state + a ``run_steps`` row in one transaction.
``schemas``   — Pydantic request/response shapes for the v1 API.
"""

from __future__ import annotations

from app.runs.enums import RunEvent, RunState, is_terminal_state
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.transitions import ALLOWED_TRANSITIONS, next_state

__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidTransitionError",
    "RunEvent",
    "RunNotFoundError",
    "RunState",
    "TerminalStateError",
    "UnknownEventError",
    "is_terminal_state",
    "next_state",
]
