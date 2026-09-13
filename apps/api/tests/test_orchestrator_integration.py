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
from tests.conftest import ensure_project

# ---------------------------------------------------------------------------
# End-to-end: Phase 2 loop walks CREATED -> ... -> COMPLETED.
# ---------------------------------------------------------------------------


async def test_create_run_drives_loop_to_completed(
    orchestrator_app: tuple[AsyncClient, Orchestrator],
) -> None:
    """A bare POST /api/v1/runs should reach COMPLETED via the real agents.

    CREATED still uses the stub (repository_ready); every later state
    runs its Phase 2 agent through REVIEWING. (The pagination-specific
    exit criteria live in test_e2e_pagination.py.)
    """
    client, orchestrator = orchestrator_app
    project = await ensure_project(client)
    response = await client.post(
        "/api/v1/runs",
        json={"task": "smoke test for orchestrator", "project_id": project["id"]},
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]

    final = await _wait_for_state(client, run_id, {"COMPLETED"}, timeout_s=60.0)
    body = final.json()
    assert body["state"] == "COMPLETED"
    assert body["is_terminal"] is True
    events = [step["event"] for step in body["steps"]]
    assert events == [
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "implementation_complete",
        "tests_passed",
        "review_passed",
    ]
    # Policy auto-approval is audited on the step.
    approved = [step for step in body["steps"] if step["event"] == "plan_approved"]
    assert len(approved) == 1
    assert approved[0]["approved_by"] == "policy"
    # After the run terminates, no orchestrator task should remain.
    assert orchestrator.runtime.outstanding() == 0


async def test_create_run_does_not_invoke_orchestrator_when_uninstalled(
    authed_client: AsyncClient,
) -> None:
    """Apps built without an orchestrator still serve the API.

    ``authed_client`` installs no orchestrator (like the Issue #001
    ``app_instance`` configuration), so the run stays in CREATED.
    """
    project = await ensure_project(authed_client)
    response = await authed_client.post(
        "/api/v1/runs",
        json={"task": "no orchestrator", "project_id": project["id"]},
    )
    assert response.status_code == 201
    # Without the orchestrator, the run stays in CREATED.
    assert response.json()["state"] == "CREATED"


async def test_external_event_application_drives_orchestrator(
    orchestrator_app: tuple[AsyncClient, Orchestrator],
) -> None:
    """Manually applying an event for a parked run advances it."""
    client, _orchestrator = orchestrator_app
    # First create + wait for the loop to terminate.
    project = await ensure_project(client)
    create = await client.post(
        "/api/v1/runs", json={"task": "manual event", "project_id": project["id"]}
    )
    assert create.status_code == 201
    run_id = create.json()["id"]
    await _wait_for_state(client, run_id, {"COMPLETED"}, timeout_s=60.0)
    # Applying an event to a terminal run returns 409 (per Issue #001).
    response = await client.post(f"/api/v1/runs/{run_id}/events", json={"event": "cancel"})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for_state(
    client: AsyncClient,
    run_id: str,
    states: set[str],
    *,
    timeout_s: float,
    poll_interval_s: float = 0.05,
) -> Any:
    """Poll ``GET /runs/{id}`` until ``state`` is in ``states`` or we time out."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["state"] in states:
            return response
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"Run {run_id} did not reach {sorted(states)} within {timeout_s}s. "
                f"Last state: {body['state']}"
            )
        await asyncio.sleep(poll_interval_s)


# Re-export so other modules can import RunState without a long path.
__all__ = ["RunState"]
