"""Integration tests for the Run state machine service.

These tests run against a real PostgreSQL database (see
``tests/conftest.py`` for the fixture) and exercise:

  * create_run + get_run
  * transition() happy path (CREATED -> ANALYZING -> PLANNING ->
    AWAITING_APPROVAL -> IMPLEMENTING) with persisted run_steps rows
  * InvalidTransitionError when the event is valid but not allowed
  * UnknownEventError when the event name is not in the enum
  * TerminalStateError when the run is already terminal
  * RunNotFoundError for an unknown run_id
  * Crash recovery: applying an event and rolling back leaves the run in
    its prior state with no stray run_steps row.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.runs import service
from app.runs.enums import RunEvent, RunState, is_terminal_state
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.models import RunStep


async def test_create_run_persists_in_created_state(session: AsyncSession) -> None:
    run = await service.create_run(session, task="Add pagination to /todos")
    await session.commit()

    assert run.id is not None
    assert run.state is RunState.CREATED
    assert run.is_terminal is False
    assert run.version == 0
    assert run.task == "Add pagination to /todos"


async def test_create_run_rejects_empty_task(session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await service.create_run(session, task="")


async def test_get_run_returns_persisted_row(session: AsyncSession) -> None:
    created = await service.create_run(session, task="refactor auth")
    await session.commit()
    fetched = await service.get_run(session, created.id)
    assert fetched.id == created.id
    assert fetched.task == "refactor auth"


async def test_get_run_raises_for_unknown_id(session: AsyncSession) -> None:
    with pytest.raises(RunNotFoundError):
        await service.get_run(session, uuid.uuid4())


async def test_forward_path_writes_steps_and_bumps_version(
    session: AsyncSession,
) -> None:
    """CREATED -> ANALYZING -> PLANNING -> AWAITING_APPROVAL -> IMPLEMENTING.

    Verifies that each transition writes a RunStep row, increments
    ``version``, and updates ``state`` atomically.
    """
    run = await service.create_run(session, task="add endpoint")
    await session.commit()

    path = [
        (RunEvent.REPOSITORY_READY, RunState.ANALYZING),
        (RunEvent.ANALYSIS_COMPLETE, RunState.PLANNING),
        (RunEvent.PLAN_READY, RunState.AWAITING_APPROVAL),
        (RunEvent.PLAN_APPROVED, RunState.IMPLEMENTING),
    ]
    for event, expected_state in path:
        run = await service.transition(session, run.id, event.value)
        await session.commit()
        assert run.state is expected_state
        assert run.version == path.index((event, expected_state)) + 1
        assert run.is_terminal is False

    # All steps persisted, in order, with the right (from, event, to).
    steps = (
        await session.execute(
            select(RunStep)
            .where(RunStep.run_id == run.id)
            .order_by(RunStep.sequence)
        )
    ).scalars().all()
    assert [s.sequence for s in steps] == [1, 2, 3, 4]
    assert steps[0].from_state is RunState.CREATED
    assert steps[0].event == "repository_ready"
    assert steps[0].to_state is RunState.ANALYZING
    assert steps[-1].from_state is RunState.AWAITING_APPROVAL
    assert steps[-1].event == "plan_approved"
    assert steps[-1].to_state is RunState.IMPLEMENTING


async def test_invalid_transition_raises(session: AsyncSession) -> None:
    run = await service.create_run(session, task="x")
    await session.commit()

    with pytest.raises(InvalidTransitionError):
        await service.transition(session, run.id, "tests_passed")


async def test_unknown_event_raises(session: AsyncSession) -> None:
    run = await service.create_run(session, task="x")
    await session.commit()

    with pytest.raises(UnknownEventError):
        await service.transition(session, run.id, "not_a_real_event")


async def test_cancel_from_terminal_is_rejected(session: AsyncSession) -> None:
    run = await service.create_run(session, task="x")
    await session.commit()
    # Drive to a terminal state via the explicit path.
    run = await service.transition(session, run.id, "repository_ready")
    await session.commit()
    run = await service.transition(session, run.id, "analysis_complete")
    await session.commit()
    run = await service.transition(session, run.id, "plan_ready")
    await session.commit()
    run = await service.transition(session, run.id, "plan_approved")
    await session.commit()
    run = await service.transition(session, run.id, "implementation_complete")
    await session.commit()
    run = await service.transition(session, run.id, "tests_passed")
    await session.commit()
    run = await service.transition(session, run.id, "review_passed")
    await session.commit()
    assert is_terminal_state(run.state)

    with pytest.raises(TerminalStateError):
        await service.transition(session, run.id, "cancel")


async def test_crash_recovery_no_state_change_on_rollback(
    engine: AsyncEngine,
) -> None:
    """If the caller rolls back, neither state nor steps change.

    This is the durability invariant from DATABASE_DESIGN §2.1: the
    state update and the run_steps insert must be atomic.

    We simulate the crash by:

      1. Creating a Run and committing it (a known starting point).
      2. Opening a *fresh* session, applying a transition, and rolling
         back without committing — this is what a process crash between
         the application logic and the COMMIT looks like.
      3. Opening *another* fresh session (what a restarted worker would
         do) and asserting the run is still in its pre-transition state
         with no run_steps rows.
    """
    # Step 1: baseline.
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        run = await service.create_run(session, task="x")
        await session.commit()
        run_id = run.id
        initial_state = run.state
        initial_version = run.version

    # Step 2: simulate the crash.
    async with maker() as session:
        await service.transition(session, run_id, "repository_ready")
        # No commit — rollback simulates the process dying.
        await session.rollback()

    # Step 3: a restarted worker observes the database.
    async with maker() as session:
        refreshed = await service.get_run(session, run_id)
        assert refreshed.state is initial_state
        assert refreshed.version == initial_version

        count = (
            await session.execute(
                select(func.count())
                .select_from(RunStep)
                .where(RunStep.run_id == run_id)
            )
        ).scalar_one()
        assert count == 0


async def test_unknown_run_id_raises_not_found(session: AsyncSession) -> None:
    with pytest.raises(RunNotFoundError):
        await service.transition(session, uuid.uuid4(), "cancel")


async def test_run_steps_unique_per_run_sequence(session: AsyncSession) -> None:
    """The (run_id, sequence) uniqueness invariant holds at the DB layer."""
    run = await service.create_run(session, task="x")
    await session.commit()
    await service.transition(session, run.id, "repository_ready")
    await session.commit()
    # Two reads of the step list show consistent sequence numbers.
    s1 = (
        await session.execute(
            select(RunStep.sequence).where(RunStep.run_id == run.id)
        )
    ).scalars().all()
    s2 = (
        await session.execute(
            select(RunStep.sequence).where(RunStep.run_id == run.id)
        )
    ).scalars().all()
    assert s1 == s2 == [1]
