"""Approval behavior tests (Issue #008, CONTEXT.md vocabulary).

Policy auto-approval (FORGE_AUTO_APPROVE=true, the Phase 2 default)
records approved_by=policy; an explicit HTTP approval records
approved_by=human; plan_rejected returns the Run to PLANNING.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def _wait_for_state(
    client: Any, run_id: str, states: set[str], *, timeout_s: float = 15.0
) -> Any:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        if response.json()["state"] in states:
            return response
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"Run {run_id} did not reach {sorted(states)} within {timeout_s}s. "
                f"Last state: {response.json()['state']}"
            )
        await asyncio.sleep(0.05)


def _approved_by(body: dict[str, Any], event: str) -> str | None:
    matches = [s for s in body["steps"] if s["event"] == event]
    assert len(matches) == 1, f"expected one {event} step, got {len(matches)}"
    return matches[0]["approved_by"]


async def test_policy_auto_approve_records_actor(
    orchestrator_app: tuple[Any, Any],
) -> None:
    """Default loop: plan approved by policy on the way to COMPLETED."""
    client, _orchestrator = orchestrator_app
    created = await client.post("/api/v1/runs", json={"task": "add pagination to /todos"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    # The loop continues past TESTING (tester → reviewer), so assert the
    # Audit trail is asserted once the run terminates, not mid-flight.
    final = await _wait_for_state(client, run_id, {"COMPLETED"})
    body = final.json()
    assert [s["event"] for s in body["steps"]] == [
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "implementation_complete",
        "tests_passed",
        "review_passed",
    ]
    assert _approved_by(body, "plan_approved") == "policy"


async def test_plan_rejected_returns_to_planning(
    manual_approval_app: tuple[Any, Any],
) -> None:
    """A human can send the Run back from AWAITING_APPROVAL to PLANNING."""
    client, _orchestrator = manual_approval_app
    created = await client.post("/api/v1/runs", json={"task": "add pagination to /todos"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    await _wait_for_state(client, run_id, {"AWAITING_APPROVAL"})
    rejected = await client.post(f"/api/v1/runs/{run_id}/events", json={"event": "plan_rejected"})
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["state"] == "PLANNING"
    assert body["steps"][-1]["event"] == "plan_rejected"


async def test_human_approval_records_actor(
    manual_approval_app: tuple[Any, Any],
) -> None:
    """Explicit HTTP approval records approved_by=human, then work proceeds."""
    client, _orchestrator = manual_approval_app
    created = await client.post("/api/v1/runs", json={"task": "add pagination to /todos"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    await _wait_for_state(client, run_id, {"AWAITING_APPROVAL"})
    approved = await client.post(f"/api/v1/runs/{run_id}/events", json={"event": "plan_approved"})
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "IMPLEMENTING"
    assert _approved_by(approved.json(), "plan_approved") == "human"

    final = await _wait_for_state(client, run_id, {"TESTING"})
    assert _approved_by(final.json(), "plan_approved") == "human"
