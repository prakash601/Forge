"""Unit tests for the orchestrator (no database).

These tests cover:

  * ``StateAgentRegistry`` mappings (default + override)
  * ``archaeologist_stub`` returns the documented event for each mapped state
  * ``InProcessRuntime`` schedule / shutdown semantics
  * ``Orchestrator.handle_transition`` schedules a task iff the driver
    has an agent for ``to_state``
  * The scheduled task re-enters ``service.transition`` with the agent's
    returned event (verified via a fake session factory + a transition
    spy that records calls)
  * Agent exceptions cause ``unrecoverable_error`` to be applied
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC
from typing import Any

import pytest

from app.orchestrator import (
    AgentContext,
    InProcessRuntime,
    Orchestrator,
    StateAgentRegistry,
    archaeologist_stub,
)
from app.runs.enums import RunEvent, RunState

# ---------------------------------------------------------------------------
# archaeologist_stub
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (RunState.CREATED, RunEvent.REPOSITORY_READY.value),
        (RunState.ANALYZING, RunEvent.ANALYSIS_COMPLETE.value),
        (RunState.PLANNING, RunEvent.PLAN_READY.value),
        (RunState.AWAITING_APPROVAL, RunEvent.PLAN_APPROVED.value),
        (RunState.IMPLEMENTING, RunEvent.CANCEL.value),
    ],
)
async def test_archaeologist_stub_returns_documented_event(state: RunState, expected: str) -> None:
    ctx = AgentContext(
        run=_fake_run(state),
        steps=(),
        request_id="req_test",
    )
    assert await archaeologist_stub.run(ctx) == expected


@pytest.mark.parametrize(
    "state",
    [
        RunState.TESTING,
        RunState.DEBUGGING,
        RunState.REVIEWING,
        RunState.COMPLETED,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.NEEDS_HUMAN,
    ],
)
async def test_archaeologist_stub_returns_none_for_unmapped(state: RunState) -> None:
    ctx = AgentContext(
        run=_fake_run(state),
        steps=(),
        request_id="req_test",
    )
    assert await archaeologist_stub.run(ctx) is None


# ---------------------------------------------------------------------------
# StateAgentRegistry
# ---------------------------------------------------------------------------


def test_state_agent_registry_defaults() -> None:
    registry = StateAgentRegistry()
    assert registry.agent_for(RunState.CREATED) is archaeologist_stub
    assert registry.agent_for(RunState.IMPLEMENTING) is archaeologist_stub
    assert registry.agent_for(RunState.TESTING) is None
    assert registry.agent_for(RunState.COMPLETED) is None


def test_state_agent_registry_register_overrides() -> None:
    registry = StateAgentRegistry()
    sentinel = _RecordingAgent("sentinel")
    registry.register(RunState.TESTING, sentinel)
    assert registry.agent_for(RunState.TESTING) is sentinel
    # Other mappings unchanged.
    assert registry.agent_for(RunState.CREATED) is archaeologist_stub


# ---------------------------------------------------------------------------
# InProcessRuntime
# ---------------------------------------------------------------------------


async def test_runtime_runs_a_simple_coroutine() -> None:
    runtime = InProcessRuntime()

    async def returns_value() -> str:
        return "ok"

    task = runtime.schedule(returns_value())
    assert isinstance(task, asyncio.Task)
    result = await task
    assert result == "ok"
    assert runtime.outstanding() == 0


async def test_runtime_schedule_after_shutdown_raises() -> None:
    runtime = InProcessRuntime()
    await runtime.shutdown()

    async def dummy() -> None:
        return None

    with pytest.raises(RuntimeError, match="shutting down"):
        runtime.schedule(dummy())


async def test_runtime_drains_outstanding_tasks_on_shutdown() -> None:
    runtime = InProcessRuntime()
    started = asyncio.Event()
    finished = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(0.05)
        finished.set()

    runtime.schedule(slow())
    await started.wait()
    assert runtime.outstanding() == 1
    await runtime.shutdown()
    assert finished.is_set()
    assert runtime.outstanding() == 0


async def test_runtime_logs_task_exceptions_without_killing_callback() -> None:
    """A task that raises must not propagate to the done callback."""
    runtime = InProcessRuntime()

    async def boom() -> None:
        raise RuntimeError("intentional")

    task = runtime.schedule(boom())
    with pytest.raises(RuntimeError, match="intentional"):
        await task
    # Runtime did not re-raise from the done callback.
    assert runtime.outstanding() == 0


# ---------------------------------------------------------------------------
# Orchestrator.handle_transition
# ---------------------------------------------------------------------------


async def test_handle_transition_no_op_when_driver_has_no_agent() -> None:
    driver = StateAgentRegistry()
    runtime = InProcessRuntime()
    orchestrator = Orchestrator(
        driver=driver,
        runtime=runtime,
        session_factory=_no_session_factory(),
    )
    # TESTING has no registered agent -> no task scheduled.
    orchestrator.handle_transition(
        run_id=uuid.uuid4(),
        from_state=RunState.IMPLEMENTING,
        to_state=RunState.TESTING,
        event=RunEvent.IMPLEMENTATION_COMPLETE.value,
        request_id="req_test",
    )
    assert runtime.outstanding() == 0


async def test_handle_transition_schedules_one_task_per_event() -> None:
    """Mapped state -> exactly one task -> exactly one transition call."""
    driver = StateAgentRegistry()
    runtime = InProcessRuntime()
    spy = _TransitionSpy()
    orchestrator = Orchestrator(
        driver=driver,
        runtime=runtime,
        session_factory=spy.session_factory(),
    )
    run_id = uuid.uuid4()

    orchestrator.handle_transition(
        run_id=run_id,
        from_state=RunState.CREATED,
        to_state=RunState.CREATED,
        event="<create>",
        request_id="req_test",
    )
    assert runtime.outstanding() == 1

    await runtime.shutdown()
    # The CREATED stub returned 'repository_ready'; the orchestrator
    # applied it via the spy.
    assert spy.applied == [(run_id, "repository_ready")]


async def test_handle_transition_does_not_recurse_synchronously() -> None:
    """The stub returning 'cancel' must not cascade in the same task.

    'cancel' moves a Run to CANCELLED, which has no registered agent,
    so no further task should be scheduled.
    """
    driver = StateAgentRegistry()
    runtime = InProcessRuntime()
    # Start the spy's view in IMPLEMENTING — the stub's documented
    # entry for that state is "cancel".
    spy = _TransitionSpy(initial_state=RunState.IMPLEMENTING)
    orchestrator = Orchestrator(
        driver=driver,
        runtime=runtime,
        session_factory=spy.session_factory(),
    )
    run_id = uuid.uuid4()
    # Manually seed the spy's state for our specific run_id.
    spy._states[run_id] = RunState.IMPLEMENTING
    orchestrator.handle_transition(
        run_id=run_id,
        from_state=RunState.IMPLEMENTING,
        to_state=RunState.IMPLEMENTING,
        event="<create>",
        request_id="req_test",
    )
    await runtime.shutdown()
    # After 'cancel' the run is in CANCELLED, which has no agent, so
    # the orchestrator must NOT schedule a follow-up task.
    assert spy.applied == [(run_id, "cancel")]


async def test_handle_transition_recovers_from_agent_exception() -> None:
    """If the agent raises, the orchestrator applies ``unrecoverable_error``."""
    driver = StateAgentRegistry()
    driver.register(RunState.CREATED, _RaisingAgent("boom"))
    runtime = InProcessRuntime()
    spy = _TransitionSpy()
    orchestrator = Orchestrator(
        driver=driver,
        runtime=runtime,
        session_factory=spy.session_factory(),
    )
    run_id = uuid.uuid4()
    orchestrator.handle_transition(
        run_id=run_id,
        from_state=RunState.CREATED,
        to_state=RunState.CREATED,
        event="<create>",
        request_id="req_test",
    )
    await runtime.shutdown()
    assert spy.applied == [(run_id, "unrecoverable_error")]


async def test_handle_transition_handles_agent_returning_none() -> None:
    """If the agent returns None, no transition is applied."""
    driver = StateAgentRegistry()
    driver.register(RunState.CREATED, _StaticAgent("noop", return_value=None))
    runtime = InProcessRuntime()
    spy = _TransitionSpy()
    orchestrator = Orchestrator(
        driver=driver,
        runtime=runtime,
        session_factory=spy.session_factory(),
    )
    run_id = uuid.uuid4()
    orchestrator.handle_transition(
        run_id=run_id,
        from_state=RunState.CREATED,
        to_state=RunState.CREATED,
        event="<create>",
        request_id="req_test",
    )
    await runtime.shutdown()
    assert spy.applied == []


async def test_orchestrator_sweep_is_a_noop_in_phase_1() -> None:
    orchestrator = Orchestrator(
        driver=StateAgentRegistry(),
        runtime=InProcessRuntime(),
        session_factory=_no_session_factory(),
    )
    assert await orchestrator.sweep() == 0


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _fake_run(state: RunState) -> Any:
    """A minimal stand-in for ``Run`` that AgentContext can hold.

    AgentContext accepts a real ``Run`` in production; the unit tests
    only inspect ``.state``, ``.id``, ``.task``, ``.version``, and
    ``.created_at``. We provide those.
    """
    from datetime import datetime

    class _FakeRun:
        def __init__(self) -> None:
            self.id = uuid.uuid4()
            self.state = state
            self.task = "fake"
            self.version = 0
            self.created_at = datetime.now(UTC)

    return _FakeRun()


class _RecordingAgent:
    """An Agent whose ``run`` returns a configurable event string."""

    def __init__(self, name: str, return_value: str | None = "plan_ready") -> None:
        self.name = name
        self.return_value = return_value
        self.calls = 0

    async def run(self, context: AgentContext) -> str | None:
        self.calls += 1
        return self.return_value


class _RaisingAgent:
    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, context: AgentContext) -> str:
        raise RuntimeError(f"{self.name} kaboom")


_StaticAgent = _RecordingAgent  # alias for readability in one test


class _TransitionSpy:
    """A fake ``session_factory`` whose ``session.transition`` records calls.

    Each call to the factory yields a fresh RecordingTransitionSession
    that mimics the tiny surface the orchestrator actually uses
    (``.get``, ``.execute``, ``.add``, ``.flush``, ``.commit``,
    ``.rollback``, ``.close``). The orchestrator invokes
    ``app.runs.service.transition`` directly — that is patched at the
    module level (see ``_patch_apply_transition`` fixture).
    """

    def __init__(self, initial_state: RunState = RunState.CREATED) -> None:
        self.applied: list[tuple[uuid.UUID, str]] = []
        self._initial_state = initial_state
        # Track per-run state. The orchestrator only knows about one
        # run per test, so a single ``last_run_id`` is enough; this
        # also keeps the dict simple for tests that re-use the spy.
        self._states: dict[uuid.UUID, RunState] = {}

    def state_of(self, run_id: uuid.UUID) -> RunState:
        return self._states.get(run_id, self._initial_state)

    def session_factory(self) -> Callable[[], Awaitable[_RecordingTransitionSession]]:
        spy = self

        async def factory() -> _RecordingTransitionSession:
            return _RecordingTransitionSession(spy)

        return factory


class _RecordingTransitionSession:
    """Pretends to be an AsyncSession for the orchestrator's purpose.

    It loads a fake Run (whose state matches the requested transition's
    from_state), records the event the orchestrator applies, and
    commits cleanly. This is enough to exercise the orchestrator's
    scheduling + dispatch logic without a real database.

    The session is shared across tasks (a single ``_TransitionSpy``
    instance creates one session per factory call, but the spy itself
    is shared). State is tracked globally per run_id so a sequence of
    agent invocations sees a coherent view.
    """

    def __init__(self, spy: _TransitionSpy) -> None:
        self._spy = spy

    async def get(self, _model: Any, run_id: Any) -> Any:
        current_state = self._spy.state_of(run_id)
        return _MakeFakeRun(run_id, current_state)

    async def execute(self, _stmt: Any) -> Any:
        # Used for the steps query in _load_run_and_steps; return empty.
        class _EmptyScalars:
            def all(self) -> list[Any]:
                return []

        class _EmptyResult:
            def scalars(self) -> _EmptyScalars:
                return _EmptyScalars()

        return _EmptyResult()

    def add(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass

    # The orchestrator calls ``app.runs.service.transition`` (not a
    # method on this object). Patch it via monkeypatching at the module
    # level; see the test that uses this spy.


def _no_session_factory() -> Any:
    """A session factory that returns a session with no Run loaded.

    Used for tests where ``handle_transition`` should be a no-op (no
    task scheduled). Never invoked because the runtime has no work.
    """

    async def factory() -> Any:
        raise AssertionError(
            "_no_session_factory.session() was called — the test should "
            "not have scheduled any tasks."
        )

    return factory


class _MakeFakeRun:
    """Helper for ``_RecordingTransitionSession.get``.

    Subclasses ``Run`` would require a full SQLAlchemy declarative
    setup; we instead return an object that satisfies the duck-typed
    surface the orchestrator reads.
    """

    def __init__(self, run_id: Any, state: RunState) -> None:
        self.id = run_id
        self.state = state
        self.task = "fake"
        self.version = 0
        from datetime import datetime

        self.created_at = datetime.now(UTC)


# Reach into the orchestrator module to patch ``apply_transition``.
# This avoids the need for a real DB in unit tests.
@pytest.fixture(autouse=True)
def _patch_apply_transition(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``apply_transition`` with a recording shim for unit tests.

    The shim advances the spy's per-run state using the real transition
    table so a sequence of agent invocations sees a coherent view.
    """
    from app.orchestrator import orchestrator as orch_mod

    original = orch_mod.apply_transition

    async def recording(session: Any, run_id: Any, event: str) -> Any:
        spy = getattr(session, "_spy", None)
        if spy is None:
            return None
        spy.applied.append((run_id, event))
        # Advance the spy's view of the run's state via the real
        # transition table. Falls back to leaving the state unchanged
        # if the transition is invalid (matches real behavior).
        from app.runs.transitions import ALLOWED_TRANSITIONS

        current = spy.state_of(run_id)
        try:
            next_state = ALLOWED_TRANSITIONS[(current, RunEvent(event))]
        except (KeyError, ValueError):
            return None
        spy._states[run_id] = next_state
        return None

    monkeypatch.setattr(orch_mod, "apply_transition", recording)
    yield
    monkeypatch.setattr(orch_mod, "apply_transition", original)
