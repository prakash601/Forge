"""In-process asyncio-task scheduler for the orchestrator.

The runtime owns the asyncio loop's view of agent tasks. It:

  * Schedules a task per :meth:`schedule` call.
  * Tracks outstanding tasks in a set so :meth:`shutdown` can wait
    for them to drain (or cancel them).
  * Surfaces task exceptions via structured logging — a failed agent
    must never silently kill the orchestrator.

Phase 1 implementation only. A future issue replaces this with an
out-of-process runtime (queue consumer, HTTP worker) behind the same
interface.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


class InProcessRuntime:
    """Schedule callables as asyncio tasks with bounded error handling.

    The runtime is intentionally minimal: it does not know about Runs,
    transitions, or agents. Its only job is to run a coroutine safely.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()
        self._shutdown = False

    def schedule(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Schedule ``coro`` on the current event loop.

        The task is added to an internal set so :meth:`shutdown` can
        observe it. If scheduling after :meth:`shutdown``, the coroutine
        is closed and a ``RuntimeError`` is raised — there is no point
        starting work the orchestrator has already torn down.

        Type note: callers pass a coroutine *object* (the result of
        calling an ``async def``), not an ``Awaitable``. The cast is a
        formality; mypy can't see that ``create_task`` accepts a
        coroutine that has been wrapped in an ``Awaitable``.
        """
        if self._shutdown:
            # Best-effort cleanup of the coroutine we won't run.
            try:
                coro.close()
            except Exception:  # pragma: no cover - defensive
                pass
            raise RuntimeError("InProcessRuntime is shutting down; cannot schedule new tasks.")

        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            # The agent layer should have caught and translated its own
            # errors, so anything that escapes is a bug. Log loudly;
            # do not re-raise (we are in a callback).
            log.error(
                "orchestrator_task_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                exc_info=True,
            )

    def outstanding(self) -> int:
        """Number of tasks currently in flight. Used by tests."""
        return len(self._tasks)

    async def shutdown(self, *, timeout: float = 5.0) -> None:
        """Wait for outstanding tasks to finish, then cancel any stragglers.

        Idempotent. After ``shutdown`` returns, :meth:`schedule` raises.
        """
        if self._shutdown:
            return
        self._shutdown = True

        if not self._tasks:
            return

        # Give tasks a chance to finish naturally.
        pending = list(self._tasks)
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
        for task in done:
            if not task.cancelled() and task.exception() is not None:
                log.warning(
                    "orchestrator_task_ended_with_error_during_shutdown",
                    error_type=type(task.exception()).__name__,
                    error_message=str(task.exception()),
                )
        for task in still_pending:
            task.cancel()
        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)

        self._tasks.clear()


# Convenience type alias used by the orchestrator module.
TaskFactory = Callable[[Awaitable[Any]], asyncio.Task[Any]]

__all__ = ["InProcessRuntime", "TaskFactory"]
