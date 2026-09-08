"""File-tool tests: confinement, read/list/search, write/edit."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from forge_worker.sandbox import LocalWorkspaceExecutor
from forge_worker.sandbox.errors import (
    BINARY_FILE,
    EDIT_AMBIGUOUS,
    EDIT_NO_MATCH,
    FILE_NOT_FOUND,
    PATH_OUTSIDE_WORKSPACE,
    PROTECTED_PATH,
    ToolError,
)


async def test_write_then_read_roundtrip(executor: LocalWorkspaceExecutor) -> None:
    result = await executor.write_file("notes/hello.txt", "hello\nworld\n")
    assert result.path == "notes/hello.txt"
    assert result.checksum_sha256 == sha256(b"hello\nworld\n").hexdigest()

    content = await executor.read_file("notes/hello.txt")
    assert content.content == "hello\nworld\n"
    assert (content.start_line, content.end_line) == (1, 2)


async def test_read_file_line_range(executor: LocalWorkspaceExecutor) -> None:
    await executor.write_file("code.txt", "one\ntwo\nthree\nfour\n")
    content = await executor.read_file("code.txt", start_line=2, end_line=3)
    assert content.content == "two\nthree\n"
    assert (content.start_line, content.end_line) == (2, 3)


async def test_read_missing_file_fails(executor: LocalWorkspaceExecutor) -> None:
    with pytest.raises(ToolError) as exc_info:
        await executor.read_file("nope.txt")
    assert exc_info.value.code == FILE_NOT_FOUND


async def test_read_binary_file_rejected(executor: LocalWorkspaceExecutor) -> None:
    await executor.write_file("blob.bin", "text plus \x00 null byte")
    with pytest.raises(ToolError) as exc_info:
        await executor.read_file("blob.bin")
    assert exc_info.value.code == BINARY_FILE


@pytest.mark.parametrize(
    "tool",
    ["read_file", "write_file", "list_files", "search_code"],
)
async def test_traversal_paths_rejected(executor: LocalWorkspaceExecutor, tool: str) -> None:
    method = getattr(executor, tool)
    for evil in ("../escape.txt", "a/../../escape.txt", "/etc/passwd"):
        if tool == "read_file":
            coro = method(evil)
        elif tool == "write_file":
            coro = method(evil, "x")
        elif tool == "list_files":
            coro = method(evil)
        else:
            coro = method("query", evil)
        with pytest.raises(ToolError) as exc_info:
            await coro
        assert exc_info.value.code == PATH_OUTSIDE_WORKSPACE, evil


async def test_write_inside_protected_git_dir_rejected(
    executor: LocalWorkspaceExecutor,
) -> None:
    with pytest.raises(ToolError) as exc_info:
        await executor.write_file(".git/evil.txt", "x")
    assert exc_info.value.code == PROTECTED_PATH


async def test_list_files_with_pattern(executor: LocalWorkspaceExecutor) -> None:
    await executor.write_file("src/a.py", "x")
    await executor.write_file("src/b.txt", "x")
    await executor.write_file("src/nested/c.py", "x")
    assert await executor.list_files("src", "*.py") == [
        "src/a.py",
        "src/nested/c.py",
    ]


async def test_list_files_defaults_to_workspace_root(
    executor: LocalWorkspaceExecutor,
) -> None:
    await executor.write_file("top.txt", "x")
    assert await executor.list_files() == ["top.txt"]


async def test_search_code_finds_snippets(executor: LocalWorkspaceExecutor) -> None:
    await executor.write_file("src/auth.py", "def login():\n    return oauth()\n")
    await executor.write_file("src/other.py", "nothing here\n")
    matches = await executor.search_code("oauth", "src")
    assert [(m.path, m.line) for m in matches] == [("src/auth.py", 2)]
    assert "oauth" in matches[0].snippet


async def test_search_code_respects_max_results(
    executor: LocalWorkspaceExecutor,
) -> None:
    for i in range(5):
        await executor.write_file(f"f{i}.txt", "needle\nneedle\n")
    matches = await executor.search_code("needle", ".", max_results=3)
    assert len(matches) == 3


async def test_edit_file_replaces_once_and_returns_diff(
    executor: LocalWorkspaceExecutor,
) -> None:
    await executor.write_file("app.py", "a = 1\nb = 2\n")
    result = await executor.edit_file("app.py", "a = 1", "a = 42")
    assert "-a = 1" in result.diff
    assert "+a = 42" in result.diff
    content = await executor.read_file("app.py")
    assert content.content == "a = 42\nb = 2\n"


async def test_edit_file_no_match_fails(executor: LocalWorkspaceExecutor) -> None:
    await executor.write_file("app.py", "a = 1\n")
    with pytest.raises(ToolError) as exc_info:
        await executor.edit_file("app.py", "missing", "x")
    assert exc_info.value.code == EDIT_NO_MATCH


async def test_edit_file_ambiguous_match_fails(
    executor: LocalWorkspaceExecutor,
) -> None:
    await executor.write_file("app.py", "x = 1\nx = 1\n")
    with pytest.raises(ToolError) as exc_info:
        await executor.edit_file("app.py", "x = 1", "x = 2")
    assert exc_info.value.code == EDIT_AMBIGUOUS


async def test_file_tools_do_not_escape_workspace(
    executor: LocalWorkspaceExecutor, tmp_path: Path
) -> None:
    await executor.write_file("inner.txt", "data")
    assert not (tmp_path / "escape.txt").exists()
    assert (tmp_path / "ws" / "inner.txt").exists()
