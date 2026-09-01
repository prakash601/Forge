"""HTTP-level integration tests for the Runs API (v1).

Exercises the three endpoints defined for Issue #001:

  * ``POST /api/v1/runs``
  * ``POST /api/v1/runs/{id}/events``
  * ``GET  /api/v1/runs/{id}``

Plus error paths: 404 unknown run, 409 invalid transition, 409 terminal,
422 unknown event.

These tests use the same Postgres-backed fixture as the service tests
(``tests/conftest.py``).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_create_run_returns_201_with_created_state(
    client: AsyncClient,
) -> None:
    response = await client.post("/api/v1/runs", json={"task": "add /todos pagination"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "CREATED"
    assert body["is_terminal"] is False
    assert body["version"] == 0
    assert body["task"] == "add /todos pagination"
    assert body["steps"] == []


async def test_create_run_rejects_empty_task(client: AsyncClient) -> None:
    response = await client.post("/api/v1/runs", json={"task": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


async def test_get_run_404_envelope(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/runs/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "request_id" in body["error"]


async def test_apply_event_happy_path_records_steps(
    client: AsyncClient,
) -> None:
    created = (await client.post("/api/v1/runs", json={"task": "x"})).json()

    r1 = await client.post(
        f"/api/v1/runs/{created['id']}/events",
        json={"event": "repository_ready"},
    )
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["state"] == "ANALYZING"
    assert body["version"] == 1
    assert len(body["steps"]) == 1
    assert body["steps"][0]["event"] == "repository_ready"
    assert body["steps"][0]["from_state"] == "CREATED"
    assert body["steps"][0]["to_state"] == "ANALYZING"


async def test_apply_unknown_event_returns_422(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/runs", json={"task": "x"})).json()
    response = await client.post(
        f"/api/v1/runs/{created['id']}/events",
        json={"event": "not_a_real_event"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


async def test_apply_invalid_transition_returns_409(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/runs", json={"task": "x"})).json()
    response = await client.post(
        f"/api/v1/runs/{created['id']}/events",
        json={"event": "tests_passed"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert "tests_passed" in body["error"]["message"]


async def test_apply_event_to_terminal_returns_409(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/runs", json={"task": "x"})).json()
    # Walk to COMPLETED.
    path = [
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "implementation_complete",
        "tests_passed",
        "review_passed",
    ]
    for event in path:
        response = await client.post(
            f"/api/v1/runs/{created['id']}/events",
            json={"event": event},
        )
        assert response.status_code == 200, response.text

    # Now any further event must 409.
    response = await client.post(
        f"/api/v1/runs/{created['id']}/events",
        json={"event": "cancel"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "CONFLICT"
    assert "terminal" in body["error"]["message"].lower()


async def test_apply_event_to_unknown_run_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/runs/00000000-0000-0000-0000-000000000000/events",
        json={"event": "cancel"},
    )
    assert response.status_code == 404


async def test_get_run_after_transitions_returns_full_timeline(
    client: AsyncClient,
) -> None:
    created = (await client.post("/api/v1/runs", json={"task": "x"})).json()
    for event in ("repository_ready", "analysis_complete"):
        await client.post(
            f"/api/v1/runs/{created['id']}/events", json={"event": event}
        )
    response = await client.get(f"/api/v1/runs/{created['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "PLANNING"
    assert body["version"] == 2
    assert [s["sequence"] for s in body["steps"]] == [1, 2]
    assert [s["event"] for s in body["steps"]] == ["repository_ready", "analysis_complete"]


@pytest.mark.parametrize("bad_uuid", ["not-a-uuid", "12345", " "])
async def test_get_run_with_malformed_uuid_returns_422(
    client: AsyncClient, bad_uuid: str
) -> None:
    # FastAPI's path validation produces 422 for unparseable UUIDs.
    response = await client.get(f"/api/v1/runs/{bad_uuid}")
    assert response.status_code == 422
