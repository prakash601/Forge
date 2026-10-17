"""Tests for Prometheus metrics (Phase 4, Issue #019)."""

from __future__ import annotations

import re

from httpx import AsyncClient

from app.llm import metrics as llm_metrics
from app.metrics import registry


def _counter_value(text: str, name: str, labels: str) -> float | None:
    """Parse one ``name{labels} value`` sample from the exposition."""
    pattern = re.compile(rf"^{re.escape(name)}\{{{re.escape(labels)}\}}\s+([0-9.eE+-]+)$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    return None


async def test_metrics_open_without_auth(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "forge_http_requests_total" in response.text


async def test_metrics_excludes_itself(authed_client: AsyncClient) -> None:
    await authed_client.get("/metrics")
    await authed_client.get("/metrics")
    text = (await authed_client.get("/metrics")).text
    assert 'route="/metrics"' not in text


async def test_http_requests_counted_with_template(authed_client: AsyncClient) -> None:
    before = (await authed_client.get("/metrics")).text
    before_v = (
        _counter_value(
            before,
            "forge_http_requests_total",
            'method="GET",route="/api/v1/projects",status="200"',
        )
        or 0.0
    )
    await authed_client.get("/api/v1/projects")
    after = (await authed_client.get("/metrics")).text
    after_v = _counter_value(
        after,
        "forge_http_requests_total",
        'method="GET",route="/api/v1/projects",status="200"',
    )
    assert after_v is not None and after_v == before_v + 1.0


async def test_run_lifecycle_counters(authed_client: AsyncClient) -> None:
    from tests.conftest import ensure_project

    project = await ensure_project(authed_client)
    created = await authed_client.post(
        "/api/v1/runs", json={"task": "metered", "project_id": project["id"]}
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    await authed_client.post(f"/api/v1/runs/{run_id}/events", json={"event": "cancel"})
    text = (await authed_client.get("/metrics")).text
    assert "forge_runs_created_total" in text
    cancel_v = _counter_value(text, "forge_run_events_total", 'approved_by="none",event="cancel"')
    assert cancel_v is not None and cancel_v >= 1.0
    assert "forge_run_duration_seconds_bucket" in text
    assert "forge_runs_current_by_state" in text


async def test_llm_bridge_reflects_counters(authed_client: AsyncClient) -> None:
    llm_metrics.record_call(provider="fake", model="fake-llm", outcome="success")
    llm_metrics.record_tokens(provider="fake", model="fake-llm", input_tokens=10, output_tokens=5)
    text = (await authed_client.get("/metrics")).text
    calls_v = _counter_value(
        text,
        "forge_llm_calls_total",
        'model="fake-llm",outcome="success",provider="fake"',
    )
    assert calls_v is not None and calls_v >= 1.0
    assert 'direction="input"' in text and 'direction="output"' in text


async def test_runs_by_state_lists_states(authed_client: AsyncClient) -> None:
    text = (await authed_client.get("/metrics")).text
    assert 'forge_runs_current_by_state{state="CREATED"}' in text


def test_record_helpers_do_not_raise() -> None:
    registry.record_http_request(method="GET", route="/x", status=200)
    registry.record_run_created()
    registry.record_run_event(event="cancel", approved_by=None)
    registry.observe_run_duration(1.5)
    payload, content_type = registry.render_latest()
    assert content_type.startswith("text/plain")
    assert len(payload) > 0
