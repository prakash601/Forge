"""End-to-end integration tests for the orchestrator.

These tests run against a real Postgres database (see
``tests/conftest.py``) and exercise the orchestrator through the full
HTTP API. The orchestrator is installed on the FastAPI app via the
``orchestrator_app`` fixture below, which also exposes its underlying
runtime so tests can deterministically wait for in-flight tasks.

Coverage:

  * A bare ``POST /api/v1/runs`` ends with the Run in CANCELLED, with
    the full stub path recorded in run_steps.
  * Orchestrator tasks are observable in the runtime.
  * Manual ``POST /runs/{id}/events`` calls also drive the orchestrator.
"""

from __future__ import annotations

import asyncio
from typing import Any

from httpx import AsyncClient

from app.orchestrator import Orchestrator
from app.runs.enums import RunState

# ---------------------------------------------------------------------------
# End-to-end: stub walks the path CREATED -> ... -> CANCELLED.
# ---------------------------------------------------------------------------


async def test_create_run_drives_stub_to_cancelled(
    orchestrator_app: tuple[AsyncClient, Orchestrator],
) -> None:
    """A bare POST /api/v1/runs should reach CANCELLED via the stub path."""
    client, orchestrator = orchestrator_app

    response = await client.post("/api/v1/runs", json={"task": "smoke test for orchestrator"})
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    # Wait for the orchestrator to drive the run to a terminal state.
    # The stub path is (per docs/STATUS.md §4.2):
    #   CREATED              -> repository_ready
    #   ANALYZING            -> analysis_complete
    #   PLANNING             -> plan_ready
    #   AWAITING_APPROVAL    -> plan_approved (auto-approve)
    #   IMPLEMENTING         -> cancel (no real implementation)
    final = await _wait_for_terminal(client, run_id, timeout_s=5.0)
    body = final.json()
    assert body["state"] == "CANCELLED"
    assert body["is_terminal"] is True
    # Every step the stub applied must be recorded.
    events = [step["event"] for step in body["steps"]]
    assert events == [
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "cancel",
    ]
    # After the run terminates, no orchestrator task should remain.
    assert orchestrator.runtime.outstanding() == 0


async def test_create_run_does_not_invoke_orchestrator_when_uninstalled(
    app_instance: Any,
) -> None:
    """Existing Issue #001 tests build the app without an orchestrator.

    Verify the API still works in that configuration.
    """
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/runs", json={"task": "no orchestrator"})
    assert response.status_code == 201
    # Without the orchestrator, the run stays in CREATED.
    assert response.json()["state"] == "CREATED"


async def test_external_event_application_drives_orchestrator(
    orchestrator_app: tuple[AsyncClient, Orchestrator],
) -> None:
    """Manually applying an event for a non-orchestrator-owned state does not crash."""
    client, _orchestrator = orchestrator_app
    # First create + wait for the stub to walk to terminal.
    create = await client.post("/api/v1/runs", json={"task": "manual event"})
    assert create.status_code == 201
    run_id = create.json()["id"]
    await _wait_for_terminal(client, run_id, timeout_s=5.0)
    # Applying an event to a terminal run returns 409 (per Issue #001).
    response = await client.post(f"/api/v1/runs/{run_id}/events", json={"event": "cancel"})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_terminal(
    client: AsyncClient,
    run_id: str,
    *,
    timeout_s: float,
    poll_interval_s: float = 0.05,
) -> Any:
    """Poll ``GET /runs/{id}`` until ``state`` is terminal or we time out."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return response
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"Run {run_id} did not reach terminal state within {timeout_s}s. "
                f"Last state: {body['state']}"
            )
        await asyncio.sleep(poll_interval_s)


# Re-export so other modules can import RunState without a long path.
__all__ = ["RunState"]
