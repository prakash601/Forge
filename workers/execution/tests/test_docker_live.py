"""Live-daemon integration tests for the Docker sandbox (Issue #017).

Needs a Docker daemon and the ``forge-sandbox:0.1.0`` image (built
from ``infra/docker/sandbox.Dockerfile``). Both are present on CI
runners and dev machines with Docker; elsewhere these tests skip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_worker.sandbox import DockerExecutorConfig, DockerWorkspaceExecutor

IMAGE = "forge-sandbox:0.1.0"
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "todo-app"


def _daemon_available() -> bool:
    try:
        import docker
    except ImportError:
        return False
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


def _image_present() -> bool:
    try:
        import docker
        from docker.errors import ImageNotFound

        try:
            docker.from_env().images.get(IMAGE)
            return True
        except ImageNotFound:
            return False
    except Exception:
        return False


requires_docker = pytest.mark.skipif(not _daemon_available(), reason="no Docker daemon reachable")
requires_image = pytest.mark.skipif(not _image_present(), reason=f"{IMAGE} not built")


async def _seed(
    tmp_path: Path, run_id: str, config: DockerExecutorConfig | None = None
) -> DockerWorkspaceExecutor:
    return await DockerWorkspaceExecutor.create(
        tmp_path, run_id, FIXTURE_DIR, config or DockerExecutorConfig(run_id=run_id)
    )


@requires_docker
@requires_image
async def test_live_pytest_cycle(tmp_path: Path) -> None:
    """The fixture suite passes inside the container."""
    ex = await _seed(tmp_path, "run-live-pytest")
    result = await ex.run_command(
        ["python", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
        timeout_seconds=300.0,
    )
    assert result.exit_code == 0, result.stderr_preview
    assert result.stdout_artifact.is_file()


@requires_docker
@requires_image
async def test_live_secrets_absent_from_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host secrets never enter the container (proved by a guard test)."""
    monkeypatch.setenv("DATABASE_URL", "postgres://live-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_live-secret")
    monkeypatch.setenv("FORGE_JWT_SECRET", "live-secret")
    ex = await _seed(tmp_path, "run-live-secrets")
    guard = (
        "import os\n"
        "def test_no_host_secrets():\n"
        '    for key in ("DATABASE_URL", "GITHUB_TOKEN", "FORGE_JWT_SECRET"):\n'
        "        assert key not in os.environ, key\n"
        '    assert not any(k.startswith("FORGE_") for k in os.environ)\n'
    )
    await ex.write_file("test_env_guard.py", guard)
    try:
        result = await ex.run_command(
            ["python", "-m", "pytest", "test_env_guard.py", "-q", "-p", "no:cacheprovider"],
            timeout_seconds=120.0,
        )
        assert result.exit_code == 0, result.stdout_preview + result.stderr_preview
    finally:
        host_guard = ex.workspace_path / "test_env_guard.py"
        if host_guard.exists():
            host_guard.unlink()


@requires_docker
@requires_image
async def test_live_oom_maps_to_resource_limit(tmp_path: Path) -> None:
    """A tiny container cannot survive a memory hog (proves limits apply)."""
    import asyncio as _asyncio

    from forge_worker.sandbox.docker import DockerExecutorConfig as _Cfg
    from forge_worker.sandbox.errors import SANDBOX_RESOURCE_LIMIT, ToolError

    ex = await _seed(tmp_path, "run-live-oom", _Cfg(run_id="run-live-oom", memory_mb=64))
    hog = (
        "def test_hog():\n"
        "    blobs = []\n"
        "    while True:\n"
        "        blobs.append(bytearray(8 * 1024 * 1024))\n"
    )
    await ex.write_file("test_hog.py", hog)
    try:
        with pytest.raises(ToolError) as err:
            await _asyncio.wait_for(
                ex.run_command(
                    ["python", "-m", "pytest", "test_hog.py", "-q", "-p", "no:cacheprovider"],
                    timeout_seconds=120.0,
                ),
                timeout=150.0,
            )
        assert err.value.code == SANDBOX_RESOURCE_LIMIT
    finally:
        host_hog = ex.workspace_path / "test_hog.py"
        if host_hog.exists():
            host_hog.unlink()


def test_docker_build_context_has_requirements() -> None:
    """The image build context exists (runs everywhere, no daemon needed)."""
    assert (REPO_ROOT / "infra" / "docker" / "sandbox.Dockerfile").is_file()
    assert (FIXTURE_DIR / "requirements.txt").is_file()
