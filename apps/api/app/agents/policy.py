"""Policy auto-approval for plans (Issue #008, CONTEXT.md vocabulary).

When ``FORGE_AUTO_APPROVE`` is true (the Phase 2 default), this agent is
registered for ``AWAITING_APPROVAL`` and approves every plan as a
*machine policy* act. The orchestrator records ``approved_by=policy``
on the step via :attr:`approval_actor`, so a policy approval is never
mistaken for a human one. Human approval UX arrives in Phase 3.
"""

from __future__ import annotations

from typing import Any


class PolicyAutoApproveAgent:
    """Approve any plan under policy. Returns ``plan_approved``."""

    name: str = "policy_auto_approve"
    approval_actor: str = "policy"

    async def run(self, context: Any) -> str | None:
        return "plan_approved"


__all__ = ["PolicyAutoApproveAgent"]
