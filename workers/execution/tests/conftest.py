"""Shared fixtures for execution-worker tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from forge_worker.sandbox import ExecutorConfig, LocalWorkspaceExecutor

WORKER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKER_DIR.parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "todo-app"
VENV_DIR = WORKER_DIR / ".venvs" / "todo-app"


def make_executor(
    workspace: Path, run_id: str = "run-test", **kwargs: Any
) -> LocalWorkspaceExecutor:
    """Build an executor over an existing workspace directory."""
    workspace.mkdir(parents=True, exist_ok=True)
    config = ExecutorConfig(run_id=run_id, **kwargs)
    return LocalWorkspaceExecutor(workspace, config)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    return path


@pytest.fixture()
def executor(workspace: Path) -> LocalWorkspaceExecutor:
    return make_executor(workspace)


async def seed_workspace(tmp_path: Path, run_id: str = "run-seed") -> LocalWorkspaceExecutor:
    """Copy the fixture into a per-run dir with git init (via the interface)."""
    return await LocalWorkspaceExecutor.create(
        tmp_path, run_id, FIXTURE_DIR, ExecutorConfig(run_id=run_id)
    )


def _venv_ready(venv_dir: Path) -> bool:
    python = venv_dir / "bin" / "python"
    if not python.exists():
        return False
    probe = subprocess.run(  # noqa: S603 — fixed argv, test-only venv probe
        [str(python), "-c", "import fastapi, httpx, pytest"],
        capture_output=True,
        timeout=60,
    )
    return probe.returncode == 0


def _install_fixture_requirements(python: Path) -> None:
    """Install pinned fixture requirements into the venv (once per venv)."""
    uv = shutil.which("uv")
    if uv is not None:
        cmd = [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(FIXTURE_DIR / "requirements.txt"),
        ]
    else:  # Fallback when uv is unavailable; same pinned requirements.
        cmd = [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(FIXTURE_DIR / "requirements.txt"),
        ]
    subprocess.run(cmd, check=True, timeout=300)  # noqa: S603 — fixed argv, test-only venv build


@pytest.fixture(scope="session")
def todo_venv_python() -> Iterator[Path]:
    """Build the shared fixture venv once per test session (no pip in the loop).

    Reuses ``workers/execution/.venvs/todo-app`` when it already has the
    pinned requirements installed.
    """
    python = VENV_DIR / "bin" / "python"
    if not _venv_ready(VENV_DIR):
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        subprocess.run(  # noqa: S603 — fixed argv, test-only venv build
            [sys.executable, "-m", "venv", str(VENV_DIR)], check=True, timeout=120
        )
        _install_fixture_requirements(VENV_DIR / "bin" / "python")
        assert _venv_ready(VENV_DIR), "shared venv build failed"
    yield python
