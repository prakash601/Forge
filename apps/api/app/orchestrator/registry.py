"""State -> Agent registry (the ``Driver`` implementation).

The registry is a thin in-memory mapping. It is the seam where
real agents will be wired in Phase 2. For Phase 1 only the
``archaeologist_stub`` is registered, and only for the states listed in
``docs/STATUS.md`` §4.2 (Issue #002 success criteria).
"""

from __future__ import annotations

from app.orchestrator.agents import archaeologist_stub
from app.orchestrator.protocols import Agent, Driver
from app.runs.enums import RunState


class StateAgentRegistry(Driver):
    """Maps :class:`RunState` -> :class:`Agent`.

    The constructor accepts an explicit mapping so tests can swap agents
    or add states without touching the orchestrator.
    """

    def __init__(self, mapping: dict[RunState, Agent] | None = None) -> None:
        # Default mapping mirrors the Phase 1 stub.
        self._mapping: dict[RunState, Agent] = dict(mapping or {})
        if RunState.CREATED not in self._mapping:
            self._mapping[RunState.CREATED] = archaeologist_stub
        if RunState.ANALYZING not in self._mapping:
            self._mapping[RunState.ANALYZING] = archaeologist_stub
        if RunState.PLANNING not in self._mapping:
            self._mapping[RunState.PLANNING] = archaeologist_stub
        if RunState.AWAITING_APPROVAL not in self._mapping:
            self._mapping[RunState.AWAITING_APPROVAL] = archaeologist_stub
        if RunState.IMPLEMENTING not in self._mapping:
            self._mapping[RunState.IMPLEMENTING] = archaeologist_stub

    def register(self, state: RunState, agent: Agent) -> None:
        """Add or replace the agent for ``state``. Used by tests."""
        self._mapping[state] = agent

    def agent_for(self, state: object) -> Agent | None:
        # ``state`` is typed as ``object`` because the Driver protocol
        # is intentionally permissive (tests may pass duck-typed
        # states). The dict is keyed by ``RunState``, but RunState
        # inherits from ``str`` so the lookup works for enum members.
        if not isinstance(state, RunState):
            return None
        return self._mapping.get(state)

    def registered_states(self) -> set[RunState]:
        """Return the set of states the registry knows about. Useful for tests."""
        return set(self._mapping.keys())


__all__ = ["StateAgentRegistry"]
