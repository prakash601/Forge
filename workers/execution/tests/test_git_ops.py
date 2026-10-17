"""Git-tool tests: seed, status, diff, branch, commit."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_worker.sandbox import LocalWorkspaceExecutor, get_executor
from forge_worker.sandbox.errors import (
    GIT_OPERATION_FAILED,
    INVALID_INPUT,
    INVALID_RUN_ID,
    WORKSPACE_EXISTS,
    ToolError,
)
from tests.conftest import seed_workspace


async def test_create_seeds_fixture_with_clean_git_tree(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-1")
    assert (executor.workspace_path / "app" / "main.py").exists()
    assert (executor.workspace_path / ".git").is_dir()
    status = await executor.git_status()
    assert status.branch == "main"
    assert status.changed_files == ()


async def test_status_reports_changed_and_new_files(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-2")
    await executor.edit_file("app/main.py", "Todo Fixture", "Todo Fixture v2")
    await executor.write_file("notes/scratch.txt", "wip")
    status = await executor.git_status()
    assert "app/main.py" in status.changed_files
    assert "notes/scratch.txt" in status.changed_files


async def test_diff_captures_edit(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-3")
    await executor.edit_file("app/main.py", "Todo Fixture", "Todo Fixture v2")
    diff = await executor.git_diff()
    assert "app/main.py" in diff
    assert "Todo Fixture v2" in diff


async def test_branch_and_commit_roundtrip(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-4")
    assert await executor.git_create_branch("forge/task-123") == "forge/task-123"
    await executor.edit_file("app/main.py", "Todo Fixture", "Todo Fixture v2")
    sha = await executor.git_commit("feat: bump fixture title")
    assert len(sha) == 40
    status = await executor.git_status()
    assert status.branch == "forge/task-123"
    assert status.changed_files == ()
    assert await executor.git_diff() == ""


async def test_commit_without_changes_fails(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-5")
    with pytest.raises(ToolError) as exc_info:
        await executor.git_commit("feat: nothing changed")
    assert exc_info.value.code == GIT_OPERATION_FAILED


async def test_invalid_branch_name_rejected(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-6")
    for bad in ("", "-leading-dash", "has space", "double..dots", "trail/"):
        with pytest.raises(ToolError) as exc_info:
            await executor.git_create_branch(bad)
        assert exc_info.value.code == INVALID_INPUT, bad


async def test_empty_commit_message_rejected(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-git-7")
    with pytest.raises(ToolError) as exc_info:
        await executor.git_commit("   ")
    assert exc_info.value.code == INVALID_INPUT


async def test_duplicate_run_id_rejected(tmp_path: Path) -> None:
    await seed_workspace(tmp_path, "run-dup")
    with pytest.raises(ToolError) as exc_info:
        await seed_workspace(tmp_path, "run-dup")
    assert exc_info.value.code == WORKSPACE_EXISTS


async def test_invalid_run_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(ToolError) as exc_info:
        await seed_workspace(tmp_path, "../escape")
    assert exc_info.value.code == INVALID_RUN_ID


def test_registry_returns_local_executor(tmp_path: Path) -> None:
    executor = get_executor(kind="local", workspace_path=tmp_path / "ws")
    assert isinstance(executor, LocalWorkspaceExecutor)


def test_registry_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown executor kind"):
        get_executor(kind="gvisor", workspace_path=tmp_path / "ws")
