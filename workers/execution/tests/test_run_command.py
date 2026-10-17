"""run_command tests: allowlist, timeout, env scrub, output caps."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

from forge_worker.sandbox import ExecutorConfig, LocalWorkspaceExecutor, sanitize_env
from forge_worker.sandbox.errors import (
    COMMAND_NOT_ALLOWED,
    FILE_NOT_FOUND,
    PATH_OUTSIDE_WORKSPACE,
    SANDBOX_TIMEOUT,
    ToolError,
)

PYTHON_PROG = Path(sys.executable).name


def _python_executor(workspace: Path, **kwargs: Any) -> LocalWorkspaceExecutor:
    workspace.mkdir(parents=True, exist_ok=True)
    config = ExecutorConfig(run_id="run-cmd", allowed_commands=(PYTHON_PROG, "pytest"), **kwargs)
    return LocalWorkspaceExecutor(workspace, config)


async def test_disallowed_command_rejected(executor: LocalWorkspaceExecutor) -> None:
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command(["echo", "hi"])
    assert exc_info.value.code == COMMAND_NOT_ALLOWED


async def test_empty_command_rejected(executor: LocalWorkspaceExecutor) -> None:
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command([])
    assert exc_info.value.code == COMMAND_NOT_ALLOWED


async def test_python_module_form_bypasses_for_pytest_only(
    executor: LocalWorkspaceExecutor,
) -> None:
    # `python -m <non-pytest>` must still be rejected under the default allowlist.
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command([sys.executable, "-m", "http.server"], timeout_seconds=1)
    assert exc_info.value.code == COMMAND_NOT_ALLOWED


async def test_nonzero_exit_is_a_successful_tool_call(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws")
    result = await executor.run_command([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert result.exit_code == 3
    assert executor.tool_calls[-1].status == "SUCCESS"
    assert executor.tool_calls[-1].error_code is None


async def test_command_timeout_kills_process(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws")
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout_seconds=0.3,
        )
    assert exc_info.value.code == SANDBOX_TIMEOUT
    assert executor.tool_calls[-1].error_code == SANDBOX_TIMEOUT


async def test_environment_secrets_scrubbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE_E2E_PROBE", "secret")
    monkeypatch.setenv("GITHUB_E2E_PROBE", "secret")
    monkeypatch.setenv("OPENAI_E2E_PROBE", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    executor = _python_executor(tmp_path / "ws")
    result = await executor.run_command(
        [
            sys.executable,
            "-c",
            "import os, json; print(json.dumps("
            "{k: v for k, v in os.environ.items() "
            "if 'E2E_PROBE' in k or k == 'DATABASE_URL'}))",
        ]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout_preview.strip().splitlines()[-1]) == {}


def test_sanitize_env_unit() -> None:
    env = sanitize_env()
    assert "DATABASE_URL" not in env
    assert all(not key.startswith(("GITHUB_", "OPENAI_", "FORGE_")) for key in env)


def test_sanitize_env_prepends_venv(tmp_path: Path) -> None:
    env = sanitize_env(tmp_path / "venv")
    assert env["PATH"].startswith(str(tmp_path / "venv" / "bin") + os.pathsep)
    assert env["VIRTUAL_ENV"] == str(tmp_path / "venv")


async def test_output_capped_to_artifacts(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws", max_output_bytes=100)
    result = await executor.run_command([sys.executable, "-c", "print('x' * 5000)"])
    assert result.truncated is True
    assert result.stdout_artifact.stat().st_size <= 100
    assert len(result.stdout_preview) <= 4000
    # Artifact lives outside the workspace so `git status` stays clean.
    assert (tmp_path / "ws") not in result.stdout_artifact.parents
    assert ".artifacts" in result.stdout_artifact.parts


async def test_stdout_and_stderr_captured_separately(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws")
    result = await executor.run_command(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"]
    )
    assert "out" in result.stdout_preview
    assert "err" in result.stderr_preview
    assert "out" in result.stdout_artifact.read_text()
    assert "err" in result.stderr_artifact.read_text()


async def test_cwd_outside_workspace_rejected(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws")
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command([sys.executable, "-c", "pass"], cwd="../..")
    assert exc_info.value.code == PATH_OUTSIDE_WORKSPACE


async def test_missing_cwd_rejected(tmp_path: Path) -> None:
    executor = _python_executor(tmp_path / "ws")
    with pytest.raises(ToolError) as exc_info:
        await executor.run_command([sys.executable, "-c", "pass"], cwd="nodir")
    assert exc_info.value.code == FILE_NOT_FOUND
