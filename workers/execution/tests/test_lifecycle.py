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


@pytest.mark.asyncio
async def test_reap_removes_only_orphan_run_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #84: startup reaping targets crash leftovers, never the worker."""
    import sys

    from forge_worker import main as main_mod

    removed: list[str] = []

    class _FakeContainer:
        def __init__(self, name: str) -> None:
            self.name = name

        def remove(self, *, force: bool = False) -> None:
            removed.append(self.name)

    class _FakeContainers:
        def list(self, *, all: bool = False) -> list[_FakeContainer]:
            return [
                _FakeContainer("forge-12345678-1234-1234-1234-1234567890ab-0001"),
                _FakeContainer("forge-worker"),
                _FakeContainer("forge-prod-worker"),
                _FakeContainer("postgres"),
                _FakeContainer("forge-short"),
            ]

    class _FakeClient:
        containers = _FakeContainers()

    class _FakeDocker:
        @staticmethod
        def from_env(*args: object, **kwargs: object) -> _FakeClient:
            return _FakeClient()

    monkeypatch.setitem(sys.modules, "docker", _FakeDocker())
    assert await main_mod._reap_stale_sandbox_containers() == 1
    assert removed == ["forge-12345678-1234-1234-1234-1234567890ab-0001"]


@pytest.mark.asyncio
async def test_reap_returns_zero_without_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from forge_worker import main as main_mod

    class _BoomDocker:
        @staticmethod
        def from_env(*args: object, **kwargs: object) -> None:
            raise RuntimeError("no daemon")

    monkeypatch.setitem(sys.modules, "docker", _BoomDocker())
    assert await main_mod._reap_stale_sandbox_containers() == 0
