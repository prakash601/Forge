"""Tool seams for the execution worker.

Mirrors ``app.orchestrator.protocols``: callers depend only on the
``SandboxExecutor`` protocol, not on ``LocalWorkspaceExecutor``, so the
future Docker sandbox (LLD §58) slots in behind the same interface.

``ToolCallStore`` is the persistence seam for ``TOOL_CONTRACTS`` §§10/12:
every tool call records tool name, run/workspace id, status, duration,
and error code.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class FileContent:
    """A slice of a workspace file (1-based inclusive line range)."""

    path: str
    content: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class FileMatch:
    """One substring hit from ``search_code``."""

    path: str
    line: int
    snippet: str


@dataclass(frozen=True)
class WriteResult:
    path: str
    checksum_sha256: str
    bytes_written: int


@dataclass(frozen=True)
class EditResult:
    path: str
    diff: str


@dataclass(frozen=True)
class CommandResult:
    """Outcome of ``run_command``.

    A non-zero ``exit_code`` is a *successful* tool call (the command
    ran; the tests it ran failed). Only infrastructure failures raise.
    Full streams live in the artifact files; previews are capped.
    """

    exit_code: int
    stdout_artifact: Path
    stderr_artifact: Path
    duration_ms: int
    stdout_preview: str
    stderr_preview: str
    truncated: bool


@dataclass(frozen=True)
class GitStatus:
    branch: str
    changed_files: tuple[str, ...]


@dataclass(frozen=True)
class ToolCallRecord:
    """Persisted observation of one tool call (TOOL_CONTRACTS §12)."""

    id: str
    tool_name: str
    run_id: str
    workspace_id: str
    status: Literal["SUCCESS", "FAILED"]
    duration_ms: int
    error_code: str | None


@runtime_checkable
class SandboxExecutor(Protocol):
    """File, shell, and git tools confined to one run workspace."""

    @property
    def workspace_path(self) -> Path: ...

    async def read_file(
        self, path: str, start_line: int = 1, end_line: int = 200
    ) -> FileContent: ...
    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]: ...
    async def search_code(
        self, query: str, path: str = ".", max_results: int = 50
    ) -> list[FileMatch]: ...
    async def write_file(self, path: str, content: str) -> WriteResult: ...
    async def edit_file(self, path: str, old_text: str, new_text: str) -> EditResult: ...
    async def run_command(
        self,
        command: list[str],
        cwd: str = ".",
        timeout_seconds: float | None = None,
    ) -> CommandResult: ...
    async def git_status(self) -> GitStatus: ...
    async def git_diff(self) -> str: ...
    async def git_create_branch(self, branch: str) -> str: ...
    async def git_commit(self, message: str) -> str: ...


@runtime_checkable
class ToolCallStore(Protocol):
    """Persistence seam for :class:`ToolCallRecord`."""

    def save(self, record: ToolCallRecord) -> None: ...
    def list_for_run(self, run_id: str) -> list[ToolCallRecord]: ...


__all__ = [
    "CommandResult",
    "EditResult",
    "FileContent",
    "FileMatch",
    "GitStatus",
    "SandboxExecutor",
    "ToolCallRecord",
    "ToolCallStore",
    "WriteResult",
]
