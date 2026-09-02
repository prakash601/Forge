"""Concrete agent implementations.

Phase 1 ships exactly one: :class:`archaeologist_stub`. It walks a Run
along a known path with no LLM call, no I/O. The point is to prove
the orchestrator loop end-to-end. When real agents land in Phase 2 they
will be siblings of this module; the stub is expected to be deleted.

Why a separate module?
----------------------
Keeping stubs isolated from real agents makes it obvious in code review
which path is the temporary scaffolding. A future grep for
``archaeologist_stub`` should reveal every place we still rely on the
stub.
"""

from __future__ import annotations

from app.orchestrator.context import AgentContext


class _ArchaeologistStub:
    """Phase 1 stand-in for the Archaeologist agent.

    Returns the next event for the current state, per the spec in
    ``docs/STATUS.md`` §4.2:

        CREATED              -> ``repository_ready``
        ANALYZING            -> ``analysis_complete``
        PLANNING             -> ``plan_ready``
        AWAITING_APPROVAL    -> ``plan_approved`` (auto-approve)
        IMPLEMENTING         -> ``cancel`` (no real implementation)

    All other states: ``None``. The orchestrator interprets ``None``
    as "no automatic action; do not schedule another task".
    """

    name: str = "archaeologist_stub"

    async def run(self, context: AgentContext) -> str | None:
        # The stub is pure state-driven; we don't read context.run or
        # context.steps. Pass the state straight to the lookup.
        return _NEXT_EVENT.get(context.state, None)

    @staticmethod
    def _state(context: AgentContext) -> object:
        return context.state


_NEXT_EVENT: dict[object, str] = {
    "CREATED": "repository_ready",
    "ANALYZING": "analysis_complete",
    "PLANNING": "plan_ready",
    "AWAITING_APPROVAL": "plan_approved",
    "IMPLEMENTING": "cancel",
}


# Singleton instance. The protocol does not require this — agents are
# stateless — but using a single object keeps identity-based reasoning
# simple in logs.
archaeologist_stub: _ArchaeologistStub = _ArchaeologistStub()


__all__ = ["archaeologist_stub"]
