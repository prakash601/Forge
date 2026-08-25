"""Smoke tests for the execution worker lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from forge_worker.main import Worker


@pytest.mark.asyncio
async def test_worker_prints_started_message_and_exits_on_shutdown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    worker = Worker()
    task = asyncio.create_task(worker.run())

    # Wait for the worker to print its startup banner.
    banner_seen = False
    for _ in range(100):
        await asyncio.sleep(0.02)
        out = capsys.readouterr().out
        if "Forge worker started" in out:
            banner_seen = True
            break

    assert banner_seen, "Worker did not print its startup banner"

    # Trigger shutdown and wait for the worker to fully exit BEFORE pytest
    # tears down capsys. This prevents the logger from writing to a closed
    # stdout file.
    worker.request_shutdown()
    exit_code = await asyncio.wait_for(task, timeout=2.0)
    assert exit_code == 0

    # Drain any remaining buffered output so capsys stays happy.
    capsys.readouterr()


@pytest.mark.asyncio
async def test_worker_idempotent_shutdown() -> None:
    worker = Worker()
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)

    worker.request_shutdown()
    # Second call must not raise.
    worker.request_shutdown()

    exit_code = await asyncio.wait_for(task, timeout=2.0)
    assert exit_code == 0


@pytest.mark.asyncio
async def test_worker_starts_and_exits_cleanly_without_external_signal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Simulate the production path: start, see the banner, request shutdown."""
    worker = Worker()
    task = asyncio.create_task(worker.run())

    for _ in range(100):
        await asyncio.sleep(0.02)
        if "Forge worker started" in capsys.readouterr().out:
            break

    worker.request_shutdown()
    exit_code = await asyncio.wait_for(task, timeout=2.0)
    assert exit_code == 0
    capsys.readouterr()


def test_worker_settings_default_to_development() -> None:
    worker = Worker()
    assert worker.settings.environment == "development"
    assert worker.settings.log_level == "INFO"
