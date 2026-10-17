"""Phase 2 exit test (Issue #009).

Task "add pagination to /todos" walks CREATED → COMPLETED on the
fixture repo: real analysis, plan, policy approval, workspace edit,
passing tests, and an APPROVE review — with the review, test report,
and memory candidates persisted and the approval step audited.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from tests.conftest import ensure_project


async def _wait_for_state(
    client: Any, run_id: str, states: set[str], *, timeout_s: float = 60.0
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
        await asyncio.sleep(0.1)


async def test_pagination_completes_end_to_end(
    orchestrator_app: tuple[Any, Any], session: Any
) -> None:
    """The Phase 2 exit criteria, asserted after a full loop walk."""
    from app.agents.service import get_memory, get_review, get_test_result

    client, orchestrator = orchestrator_app
    project = await ensure_project(client)
    created = await client.post(
        "/api/v1/runs",
        json={"task": "add pagination to /todos", "project_id": project["id"]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    final = await _wait_for_state(client, run_id, {"COMPLETED"})
    body = final.json()
    assert body["state"] == "COMPLETED"
    assert body["is_terminal"] is True
    assert [s["event"] for s in body["steps"]] == [
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "implementation_complete",
        "tests_passed",
        "review_passed",
    ]
    approved = [s for s in body["steps"] if s["event"] == "plan_approved"]
    assert len(approved) == 1
    assert approved[0]["approved_by"] == "policy"

    run_uuid = uuid.UUID(run_id)
    report_row = await get_test_result(session, run_uuid)
    assert report_row is not None
    assert report_row.result["status"] == "PASS"
    assert report_row.result["passed"] > 0
    assert report_row.result["failed"] == 0

    review_row = await get_review(session, run_uuid)
    assert review_row is not None
    assert review_row.review["decision"] == "APPROVE"

    memory_row = await get_memory(session, run_uuid)
    assert memory_row is not None
    assert len(memory_row.candidates) >= 1

    assert orchestrator.runtime.outstanding() == 0
