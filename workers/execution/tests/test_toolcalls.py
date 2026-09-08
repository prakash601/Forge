"""ToolCall persistence: validate → execute → persist (TOOL_CONTRACTS §§10/12)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge_worker.sandbox import (
    InMemoryToolCallStore,
    LocalWorkspaceExecutor,
    ToolCallRecord,
)
from forge_worker.sandbox.errors import (
    COMMAND_NOT_ALLOWED,
    PATH_OUTSIDE_WORKSPACE,
    ToolError,
)
from tests.conftest import make_executor, seed_workspace


async def test_successful_calls_record_all_fields(tmp_path: Path) -> None:
    executor = await seed_workspace(tmp_path, "run-calls-1")
    await executor.read_file("app/main.py")
    await executor.git_status()

    records = executor.tool_calls
    assert [r.tool_name for r in records] == ["read_file", "git_status"]
    for record in records:
        assert record.run_id == "run-calls-1"
        assert record.workspace_id == "run-calls-1"
        assert record.status == "SUCCESS"
        assert record.duration_ms >= 0
        assert record.error_code is None
        assert record.id


async def test_failed_validation_still_persists(tmp_path: Path) -> None:
    executor = make_executor(tmp_path / "ws", run_id="run-calls-2")
    with pytest.raises(ToolError):
        await executor.read_file("../escape.txt")
    (record,) = executor.tool_calls
    assert record.tool_name == "read_file"
    assert record.status == "FAILED"
    assert record.error_code == PATH_OUTSIDE_WORKSPACE


async def test_failed_command_persists_error_code(
    executor: LocalWorkspaceExecutor,
) -> None:
    with pytest.raises(ToolError):
        await executor.run_command(["rm", "-rf", "/"])
    (record,) = executor.tool_calls
    assert record.tool_name == "run_command"
    assert record.status == "FAILED"
    assert record.error_code == COMMAND_NOT_ALLOWED


async def test_records_isolated_per_run(tmp_path: Path) -> None:
    store = InMemoryToolCallStore()
    first = make_executor(tmp_path / "ws-a", run_id="run-a", tool_call_store=store)
    second = make_executor(tmp_path / "ws-b", run_id="run-b", tool_call_store=store)
    await first.write_file("a.txt", "a")
    await second.write_file("b.txt", "b")
    assert [r.tool_name for r in store.list_for_run("run-a")] == ["write_file"]
    assert [r.tool_name for r in store.list_for_run("run-b")] == ["write_file"]
    assert store.list_for_run("run-unknown") == []


def test_store_lists_in_insertion_order() -> None:
    store = InMemoryToolCallStore()
    store.save(
        ToolCallRecord(
            id="1",
            tool_name="read_file",
            run_id="r",
            workspace_id="r",
            status="SUCCESS",
            duration_ms=5,
            error_code=None,
        )
    )
    store.save(
        ToolCallRecord(
            id="2",
            tool_name="git_diff",
            run_id="r",
            workspace_id="r",
            status="FAILED",
            duration_ms=7,
            error_code="GIT_OPERATION_FAILED",
        )
    )
    assert [r.id for r in store.list_for_run("r")] == ["1", "2"]


async def test_executor_without_store_still_records(
    tmp_path: Path,
) -> None:
    executor = make_executor(tmp_path / "ws", run_id="run-calls-3")
    assert executor.config.tool_call_store is None
    await executor.write_file("x.txt", "x")
    assert len(executor.tool_calls) == 1
