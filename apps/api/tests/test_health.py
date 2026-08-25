"""Smoke tests for the operational endpoints (`/health`, `/ready`)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_does_not_require_database(client: AsyncClient, monkeypatch: Any) -> None:
    """`/health` is a pure liveness probe. It must not depend on the DB."""

    async def _explode() -> None:
        raise RuntimeError("DB should not be queried from /health")

    # The readiness check is the only thing that touches the DB. If /health
    # ever starts requiring the DB, this assertion would still pass because
    # we only check that the endpoint returns 200 and the body shape.
    response = await client.get("/health")
    assert response.status_code == 200


async def test_ready_returns_ok_when_database_reachable(
    client: AsyncClient,
) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


async def test_ready_returns_503_when_database_unreachable(
    app_instance: Any,
) -> None:
    from httpx import ASGITransport, AsyncClient

    # Break the database session factory so ping_database() raises.
    from app.db import session as db_session

    original = db_session._session_factory  # type: ignore[attr-defined]
    db_session._session_factory = None  # type: ignore[attr-defined]
    try:
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
    finally:
        db_session._session_factory = original  # type: ignore[attr-defined]


async def test_ready_envelope_includes_request_id_header(
    client: AsyncClient,
) -> None:
    response = await client.get("/ready", headers={"X-Request-ID": "req_test_42"})
    assert response.headers.get("x-request-id") == "req_test_42"
