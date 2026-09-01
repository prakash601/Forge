"""Orchestrator package.

The orchestrator is responsible for driving Runs forward after each
``transition()``. It receives a notification ("a Run just moved from
state A to state B") and, if state B maps to an agent action, schedules
a task that runs the agent and applies the next event.

Phase 1 implementation: **in-process**. The interface is
transport-agnostic so a later issue can move execution to a separate
worker process without touching call sites.

Layering
--------
``protocols``  — :class:`Agent` protocol (one method, ``run``) and
                :class:`Driver` protocol (registry of state -> agent).
``agents``     — concrete agent implementations. Phase 1 ships one:
                ``archaeologist_stub``.
``registry``   — the in-memory driver that maps states to agents.
``runtime``    — the asyncio-task scheduler. Owns the in-process task
                pool and exposes ``schedule()`` / ``shutdown()``.
``orchestrator`` — the public-facing class. The API layer calls
                :meth:`Orchestrator.handle_transition` after every
                successful ``transition()`` commit.
"""

from __future__ import annotations

from app.orchestrator.agents import archaeologist_stub
from app.orchestrator.context import AgentContext
from app.orchestrator.orchestrator import Orchestrator
from app.orchestrator.protocols import Agent, Driver
from app.orchestrator.registry import StateAgentRegistry
from app.orchestrator.runtime import InProcessRuntime

__all__ = [
    "Agent",
    "AgentContext",
    "Driver",
    "InProcessRuntime",
    "Orchestrator",
    "StateAgentRegistry",
    "archaeologist_stub",
]
