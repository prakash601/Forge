"""Context object passed to agents.

Kept in its own module so adding new fields (e.g. cancellation tokens,
memory accessors, tool handles) does not require changing every agent.

Phase 1 ships only:

  * ``run``        — the current :class:`Run` (state, task, version)
  * ``steps``      — the run's history (read-only tuple)
  * ``request_id`` — correlation id for logs

The orchestrator constructs the context from the live session right
before invoking the agent, so the agent always sees the just-committed
state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.runs.enums import RunState


class _RunLike(Protocol):
    """Minimal surface agents read from the Run snapshot.

    Using a Protocol (rather than the concrete ``Run`` class) lets
    tests pass duck-typed stand-ins without spinning up SQLAlchemy.
    Production code passes a real ``Run`` instance, which satisfies
    the protocol structurally.
    """

    id: uuid.UUID
    state: RunState
    task: str
    version: int
    created_at: datetime


@dataclass(frozen=True)
class AgentContext:
    """Read-only context handed to an :class:`Agent`.

    Frozen so agents cannot accidentally mutate the snapshot they were
    given. New fields added in later issues must be Optional or
    backwards-compatible.
    """

    run: _RunLike
    steps: tuple[Any, ...]
    request_id: str

    @property
    def run_id(self) -> uuid.UUID:
        return self.run.id

    @property
    def state(self) -> RunState:
        return self.run.state

    @property
    def task(self) -> str:
        return self.run.task

    @property
    def version(self) -> int:
        return self.run.version

    @property
    def created_at(self) -> datetime:
        return self.run.created_at

    def step_count(self) -> int:
        return len(self.steps)


__all__ = ["AgentContext"]
