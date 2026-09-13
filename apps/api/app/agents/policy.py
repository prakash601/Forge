"""Policy approval for plans (Issues #008, #020; CONTEXT.md vocabulary).

Two agents:

* :class:`PolicyAutoApproveAgent` — unconditional policy approval
  (Phase 2 default; kept for explicit test wiring).
* :class:`ProjectPolicyAgent` — v1.0 gate: approves as policy when the
  global ``FORGE_AUTO_APPROVE`` env is true (legacy) or the run's
  project opted in via ``auto_approve_policy``; otherwise returns
  ``None`` so the run waits for a human. Any lookup failure also waits
  (fail safe: a human decides).

The orchestrator records ``approved_by=policy`` on the step via
:attr:`approval_actor`, so a policy approval is never mistaken for a
human one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class PolicyAutoApproveAgent:
    """Approve any plan under policy. Returns ``plan_approved``."""

    name: str = "policy_auto_approve"
    approval_actor: str = "policy"

    async def run(self, context: Any) -> str | None:
        return "plan_approved"


class ProjectPolicyAgent:
    """Approve under policy only for opted-in scope. Returns ``plan_approved`` or ``None``."""

    name: str = "project_policy"
    approval_actor: str = "policy"

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        global_auto_approve: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._global_auto_approve = global_auto_approve

    async def run(self, context: Any) -> str | None:
        if self._global_auto_approve:
            return "plan_approved"
        run_id = getattr(context, "run_id", None)
        if run_id is None:
            return None
        try:
            run_uuid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
        except (ValueError, TypeError, AttributeError):
            return None
        session = self._session_factory()
        try:
            from app.projects.service import get_project
            from app.runs.service import get_run

            try:
                run = await get_run(session, run_uuid)
            except Exception:
                return None
            if run.project_id is None:
                return None
            try:
                project = await get_project(session, run.project_id)
            except Exception:
                return None
            return "plan_approved" if project.auto_approve_policy else None
        finally:
            await session.close()


__all__ = ["PolicyAutoApproveAgent", "ProjectPolicyAgent"]
