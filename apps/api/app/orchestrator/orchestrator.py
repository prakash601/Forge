"""The Orchestrator.

This is the single class the API layer interacts with. Its
responsibilities, in order:

  1. Receive a "Run just moved from A to B" notification.
  2. Look up the agent for state B via the :class:`Driver`.
  3. If an agent is registered, schedule a task that runs the agent
     and applies the resulting event by re-entering the runs API.
  4. Optionally, on startup, sweep for Runs that were left in a
     non-terminal state by a previous API instance (no-op in Phase 1;
     the function exists so the crash-recovery contract is testable).

Design invariants
-----------------
* ``handle_transition`` is called *after* ``transition()`` has committed
  the new state. The orchestrator does not own the transaction.
* Scheduling is asynchronous. ``handle_transition`` returns immediately
  after queuing the task.
* Tasks are independent: each ``handle_transition`` schedules its own
  task. We never recurse synchronously, even if the agent's returned
  event maps to another agent (the agent's call to ``transition``
  triggers another ``handle_transition``, which schedules another
  task). This bounds stack depth to O(1).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.orchestrator.context import AgentContext
from app.orchestrator.protocols import Agent, Driver
from app.orchestrator.runtime import InProcessRuntime
from app.runs.enums import RunState
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.models import Run, RunStep
from app.runs.service import transition as apply_transition

log = get_logger(__name__)


# Type alias for the factory that builds a new session inside a task.
# The orchestrator does not own a session; each task gets its own.
SessionFactory = Callable[[], Awaitable[AsyncSession]]


class Orchestrator:
    """Drives Runs forward after each ``transition()``.

    Construction is cheap; the instance is typically created once per
    application lifetime and held on ``app.state``.
    """

    def __init__(
        self,
        *,
        driver: Driver,
        runtime: InProcessRuntime | None = None,
        session_factory: SessionFactory | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if session_factory is None and session_maker is None:
            raise ValueError("Orchestrator requires either session_factory or session_maker.")
        self._driver = driver
        self._runtime = runtime or InProcessRuntime()
        # ``session_factory`` and ``session_maker`` are the same thing
        # under two different historical names. We keep both kwargs for
        # readability; one is required.
        self._session_factory = session_factory or _maker_to_factory(session_maker)  # type: ignore[arg-type]

    @property
    def driver(self) -> Driver:
        return self._driver

    @property
    def runtime(self) -> InProcessRuntime:
        return self._runtime

    # ------------------------------------------------------------------
    # Hot path: invoked from the API layer after every successful commit.
    # ------------------------------------------------------------------
    def handle_transition(
        self,
        *,
        run_id: uuid.UUID,
        from_state: RunState,
        to_state: RunState,
        event: str = "",
        request_id: str = "",
    ) -> None:
        """Schedule an agent for ``to_state`` if one is registered.

        Returns immediately. The agent runs in a background task on the
        current asyncio loop. The ``event`` arg is accepted for logging
        context (which event triggered this state); the orchestrator
        itself does not need it for dispatch.
        """
        agent = self._driver.agent_for(to_state)
        if agent is None:
            log.debug(
                "orchestrator_noop",
                run_id=str(run_id),
                to_state=to_state.value,
                reason="no_agent_registered",
                request_id=request_id,
            )
            return

        log.info(
            "orchestrator_scheduling",
            run_id=str(run_id),
            from_state=from_state.value,
            to_state=to_state.value,
            agent=getattr(agent, "name", agent.__class__.__name__),
            request_id=request_id,
        )

        self._runtime.schedule(
            self._run_agent(
                agent=agent,
                run_id=run_id,
                request_id=request_id,
            )
        )

    async def _run_agent(
        self,
        *,
        agent: Agent,
        run_id: uuid.UUID,
        request_id: str,
    ) -> None:
        """Open a session, build context, invoke the agent, apply event.

        The agent's returned event is applied via the same chokepoint
        the API uses (``transition()``). On any error we apply
        ``unrecoverable_error`` to mark the Run as FAILED — Phase 1 has
        no retry semantics. A later issue owns retry/backoff.

        After a successful apply, we re-fire ``handle_transition`` so
        the next state gets a chance to schedule its own agent task.
        This keeps the API layer and the orchestrator in sync without
        duplicating the dispatch logic.
        """
        session = await self._session_factory()
        try:
            run, steps = await _load_run_and_steps(session, run_id)
            context = AgentContext(
                run=run,
                steps=tuple(steps),
                request_id=request_id,
            )
            try:
                next_event = await agent.run(context)
            except Exception as exc:
                log.error(
                    "orchestrator_agent_raised",
                    run_id=str(run_id),
                    agent=getattr(agent, "name", agent.__class__.__name__),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    exc_info=True,
                    request_id=request_id,
                )
                await _apply_safely(session, run_id, "unrecoverable_error", request_id)
                return

            if next_event is None:
                log.debug(
                    "orchestrator_agent_returned_none",
                    run_id=str(run_id),
                    agent=getattr(agent, "name", agent.__class__.__name__),
                    request_id=request_id,
                )
                return

            # Apply and capture the resulting from->to for the next hook.
            applied = await _apply_and_capture(session, run_id, next_event, request_id)
            if applied is not None:
                from_state, to_state = applied
                # Re-fire the hook on the new state. Because
                # ``handle_transition`` schedules a fresh task (not
                # recursion), stack depth stays bounded.
                self.handle_transition(
                    run_id=run_id,
                    from_state=from_state,
                    to_state=to_state,
                    event=next_event,
                    request_id=request_id,
                )
        finally:
            await session.close()

    # ------------------------------------------------------------------
    # Crash-recovery seam (no-op in Phase 1).
    # ------------------------------------------------------------------
    async def sweep(self) -> int:
        """Pick up Runs left in flight by a previous API instance.

        Phase 1: returns 0 (no-op). The signature exists so:

          * the crash-recovery test in ``docs/STATUS.md`` §4.3 has a
            method to call;
          * the orchestrator's restart story is testable.

        A later issue will implement durable task tracking and resume.
        """
        return 0

    async def shutdown(self) -> None:
        """Drain outstanding tasks. Called from FastAPI's lifespan shutdown."""
        await self._runtime.shutdown()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_run_and_steps(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[Run, list[RunStep]]:
    """Fetch the Run and its steps via the session."""
    from sqlalchemy import select

    run = await session.get(Run, run_id)
    if run is None:
        # The Run was deleted between the API commit and this task
        # running. Treat as a no-op: there is nothing to drive.
        raise RunNotFoundError(str(run_id))
    steps_result = await session.execute(
        select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.sequence)
    )
    steps = list(steps_result.scalars().all())
    return run, steps


async def _apply_safely(
    session: AsyncSession,
    run_id: uuid.UUID,
    event: str,
    request_id: str,
) -> tuple[RunState, RunState] | None:
    """Apply ``event`` to ``run_id`` and commit.

    Returns ``(from_state, to_state)`` on success, ``None`` on failure.
    Errors are logged and swallowed: the orchestrator must not crash
    the background task. A failed transition becomes a logged warning;
    the Run is left at its current state and the operator can intervene.
    """
    return await _apply_and_capture(session, run_id, event, request_id)


async def _apply_and_capture(
    session: AsyncSession,
    run_id: uuid.UUID,
    event: str,
    request_id: str,
) -> tuple[RunState, RunState] | None:
    """Apply ``event`` and capture the from/to states for the next hook."""
    try:
        run = await apply_transition(session, run_id, event)
        await session.commit()
        from_state: RunState = getattr(run, "_from_state", run.state)
        log.info(
            "orchestrator_event_applied",
            run_id=str(run_id),
            run_event=event,
            new_state=run.state.value,
            new_version=run.version,
            request_id=request_id,
        )
        return from_state, run.state
    except (
        InvalidTransitionError,
        TerminalStateError,
        UnknownEventError,
        RunNotFoundError,
    ) as exc:
        await session.rollback()
        log.warning(
            "orchestrator_event_rejected",
            run_id=str(run_id),
            run_event=event,
            error_type=type(exc).__name__,
            error_message=str(exc),
            request_id=request_id,
        )
        return None


def _maker_to_factory(
    maker: async_sessionmaker[AsyncSession],
) -> SessionFactory:
    """Adapt an ``async_sessionmaker`` to the ``SessionFactory`` signature."""

    async def factory() -> AsyncSession:
        return maker()

    return factory


__all__ = ["Orchestrator", "SessionFactory"]
