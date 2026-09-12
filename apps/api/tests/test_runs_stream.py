"""SSE timeline tests (Issue #010)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any


async def _collect(client: Any, run_id: str) -> list[tuple[str, Any]]:
    """Read the stream to close, parsing SSE frames."""
    events: list[tuple[str, Any]] = []
    name: str | None = None
    data_lines: list[str] = []
    async with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as response:
        assert response.status_code == 200, response.text
        async for line in response.aiter_lines():
            if line.startswith(":"):
                continue  # heartbeat
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
            elif line == "" and name is not None:
                payload = json.loads("\n".join(data_lines)) if data_lines else None
                events.append((name, payload))
                name, data_lines = None, []
    return events


async def test_stream_unknown_run_is_404(client: Any) -> None:
    response = await client.get(f"/api/v1/runs/{uuid.uuid4()}/stream")
    assert response.status_code == 404


async def test_stream_replays_walk_and_closes_on_terminal(client: Any) -> None:
    created = await client.post("/api/v1/runs", json={"task": "stream me"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    collector = asyncio.create_task(_collect(client, run_id))
    await asyncio.sleep(0.3)  # let the snapshot flush before driving events
    for event in ("repository_ready", "analysis_complete", "cancel"):
        applied = await client.post(f"/api/v1/runs/{run_id}/events", json={"event": event})
        assert applied.status_code == 200, applied.text
        await asyncio.sleep(0.3)

    events = await asyncio.wait_for(collector, timeout=20.0)
    assert events, "stream closed without frames"
    assert events[0][0] == "snapshot"
    assert events[0][1]["state"] == "CREATED"
    step_events = [data["event"] for name, data in events if name == "step_added"]
    assert step_events == ["repository_ready", "analysis_complete", "cancel"]
    states = [data["state"] for name, data in events if name == "state_changed"]
    assert states[-1] == "CANCELLED"
