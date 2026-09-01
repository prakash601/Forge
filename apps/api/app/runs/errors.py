"""Typed exceptions raised by the Run state machine service.

These are caught and translated into HTTP error envelopes at the API
boundary (see ``app/api/v1/runs.py``). Keeping them distinct lets the API
surface report the right error code and message without leaking
implementation details.
"""
from __future__ import annotations

from app.runs.enums import RunEvent, RunState


class RunNotFoundError(LookupError):
    """No Run exists with the given identifier."""

    def __init__(self, run_id: str) -> None:
        super().__init__(run_id)
        self.run_id = run_id

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Run {self.run_id!r} does not exist."


class UnknownEventError(ValueError):
    """The event name is not a known :class:`RunEvent`."""

    def __init__(self, event: str) -> None:
        super().__init__(event)
        self.event = event

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Unknown event {self.event!r}."


class InvalidTransitionError(RuntimeError):
    """The event is valid, but it is not allowed from the current state.

    Distinct from :class:`UnknownEventError` so the API can surface a
    different error code (409 vs 422) and a clearer message.
    """

    def __init__(self, current: RunState, event: RunEvent) -> None:
        super().__init__(current, event)
        self.current = current
        self.event = event

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Event {self.event.value!r} is not allowed from state {self.current.value!r}."


class TerminalStateError(RuntimeError):
    """The Run is already in a terminal state and cannot transition further.

    Raised in preference to :class:`InvalidTransitionError` so the API
    layer can return a clearer message.
    """

    def __init__(self, current: RunState, event: RunEvent) -> None:
        super().__init__(current, event)
        self.current = current
        self.event = event

    def __str__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Run is already in terminal state {self.current.value!r}; "
            f"cannot apply {self.event.value!r}."
        )


__all__ = [
    "InvalidTransitionError",
    "RunNotFoundError",
    "TerminalStateError",
    "UnknownEventError",
]
