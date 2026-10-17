"""Protocols for agents and drivers.

Both protocols are deliberately tiny so they can be implemented by:

  * test doubles in unit tests
  * in-process stubs (Phase 1, this issue)
  * out-of-process workers talking to a queue or HTTP (later issue)

The orchestrator depends only on these protocols, not on concrete
implementations, so a future transport swap is mechanical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.orchestrator.context import AgentContext


@runtime_checkable
class Agent(Protocol):
    """A unit of work that decides the next event for a Run.

    Implementations may:

      * inspect the Run's state and history (via ``context.run``,
        ``context.steps``);
      * return the name of the next :class:`app.runs.RunEvent` to apply;
      * return ``None`` to indicate "no automatic action; do not
        schedule another task from this state";
      * raise an exception, which the runtime treats as a
        ``unrecoverable_error`` transition (handled by the orchestrator,
        not by the agent).

    The return type is a plain ``str`` (or ``None``) rather than
    ``RunEvent`` so test doubles do not have to import the enum. The
    orchestrator validates the value before applying it.
    """

    name: str  # human-readable; used in logs

    async def run(self, context: AgentContext) -> str | None: ...


@runtime_checkable
class Driver(Protocol):
    """Maps a Run state to the agent that should run next.

    A driver that returns ``None`` for a state means "no automatic
    action; wait for external input (e.g. human approval)". Phase 1's
    default driver has explicit mappings for the four forward-path
    states plus IMPLEMENTING (where the stub cancels).
    """

    def agent_for(self, state: object) -> Agent | None: ...


__all__ = ["Agent", "Driver"]
