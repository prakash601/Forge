"""Run state machine service.

This module is the single chokepoint for mutating ``Run.state``. It is
deliberately small and concentrates the four invariants the rest of the
system relies on:

  1. **Validation.** The destination state is computed from the declarative
     transition table (:mod:`app.runs.transitions`). Invalid transitions
     raise :class:`InvalidTransitionError`; unknown events raise
     :class:`UnknownEventError`; terminal states raise
     :class:`TerminalStateError`.

  2. **Atomicity.** The state update on ``runs`` and the ``run_steps``
     insert land in the same database transaction. Either both commit or
     neither does — there is no path that mutates state without recording
     the event that caused it.

  3. **Optimistic concurrency.** The caller's expected ``version`` must
     match the row's current version; otherwise we raise
     :class:`InvalidTransitionError`. This protects against concurrent
     event application when, in Phase 2+, multiple components drive the
     same Run.

  4. **Terminal bookkeeping.** ``is_terminal`` is updated in the same
     transaction as the state change so operational queries do not see
     transient values.

If a future requirement demands features that this module cannot express
(for example, conditional transitions based on the task text), extend
here — do not duplicate the chokepoint elsewhere.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.runs.enums import RunEvent, RunState, is_terminal_state
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.models import Run, RunStep
from app.runs.transitions import ALLOWED_TRANSITIONS


def _coerce_event(raw: str) -> RunEvent:
    """Parse a string event into a :class:`RunEvent` enum member."""
    try:
        return RunEvent(raw)
    except ValueError as exc:
        raise UnknownEventError(raw) from exc


async def create_run(session: AsyncSession, *, task: str) -> Run:
    """Create a new Run in state ``CREATED``.

    The ``task`` is the free-form description of the work the user wants
    Forge to do. It is stored verbatim; we do not parse or validate it
    in this issue (a later issue owns task validation per
    ``DATABASE_DESIGN_v0.1.md``).
    """
    if not task or not task.strip():
        raise ValueError("task must be a non-empty string")

    now = datetime.now(UTC)
    run = Run(
        state=RunState.CREATED,
        is_terminal=False,
        task=task,
        version=0,
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()  # populate run.id
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> Run:
    """Return the Run with ``run_id`` or raise :class:`RunNotFoundError`."""
    run = await session.get(Run, run_id)
    if run is None:
        raise RunNotFoundError(str(run_id))
    return run


async def transition(
    session: AsyncSession,
    run_id: uuid.UUID,
    event: str,
    *,
    expected_version: int | None = None,
) -> Run:
    """Apply ``event`` to the Run identified by ``run_id``.

    The full sequence (read current state -> validate -> compute next
    state -> write state + insert run_step -> bump version) happens
    inside the caller's transaction. The caller is responsible for
    committing or rolling back the surrounding unit of work.

    Args:
        session: Active async session. The caller owns the transaction.
        run_id: UUID of the Run to transition.
        event: Event name from :class:`RunEvent`. Strings outside the
               enum raise :class:`UnknownEventError`.
        expected_version: If provided, the transition succeeds only when
                          the run's current ``version`` matches. Mismatch
                          raises :class:`InvalidTransitionError`. Pass
                          ``None`` to skip the check (Phase 1 callers
                          currently do; Phase 2 callers will pass the
                          version they observed when reading the run).

    Returns:
        The updated :class:`Run` (state, is_terminal, version refreshed,
        ``steps`` relationship loaded for convenience).

    Raises:
        RunNotFoundError: ``run_id`` does not exist.
        UnknownEventError: ``event`` is not in :class:`RunEvent`.
        TerminalStateError: Run is already in a terminal state.
        InvalidTransitionError: Event is valid but not allowed from the
                                current state, or ``expected_version``
                                does not match.
    """
    run_event = _coerce_event(event)

    # Read current state. We do this with an explicit select rather than
    # session.get() so that we can ALSO enforce expected_version atomically
    # in the UPDATE below.
    current_stmt = select(Run.state, Run.version).where(Run.id == run_id)
    current_row = (await session.execute(current_stmt)).first()
    if current_row is None:
        raise RunNotFoundError(str(run_id))

    current_state, current_version = current_row

    if is_terminal_state(current_state):
        raise TerminalStateError(current_state, run_event)

    if expected_version is not None and current_version != expected_version:
        raise InvalidTransitionError(current_state, run_event)

    try:
        next_state_value = ALLOWED_TRANSITIONS[(current_state, run_event)]
    except KeyError as exc:
        # The event is in the enum but not allowed from the current state.
        raise InvalidTransitionError(current_state, run_event) from exc

    next_terminal = is_terminal_state(next_state_value)
    next_sequence = current_version + 1
    now = datetime.now(UTC)

    # Atomic state update. We use ``WHERE version = current_version`` for
    # belt-and-braces optimistic concurrency even when the caller did not
    # pass expected_version; if a concurrent transaction snuck in between
    # our SELECT and UPDATE, rowcount == 0 and we raise.
    result = await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.version == current_version)
        .values(
            state=next_state_value,
            is_terminal=next_terminal,
            version=next_sequence,
            updated_at=now,
        )
    )
    if result.rowcount != 1:
        raise InvalidTransitionError(current_state, run_event)

    step = RunStep(
        run_id=run_id,
        sequence=next_sequence,
        from_state=current_state,
        event=run_event.value,
        to_state=next_state_value,
        created_at=now,
    )
    session.add(step)
    await session.flush()

    # Refresh to surface the new state/version on the returned object.
    refreshed = await session.get(Run, run_id)
    assert refreshed is not None  # we just updated it
    return refreshed


__all__ = ["create_run", "get_run", "transition"]
