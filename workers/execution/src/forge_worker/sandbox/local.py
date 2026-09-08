"""Local per-run workspace executor.

Lifecycle: ``await LocalWorkspaceExecutor.create(workspace_root, run_id,
fixture_dir)`` copies the fixture into ``workspace_root/run_id`` and
runs ``git init`` plus a seed commit; the returned instance then serves
file/shell/git tools confined to that directory.

TRUST MODEL — this is deliberately NOT a security boundary:

* Path confinement (``..``/absolute escapes rejected), no ``shell=True``,
  a default-deny command allowlist (``pytest`` only), per-command
  timeouts, capped output (full streams go to artifact files), and env
  scrubbing (``DATABASE_URL``, ``GITHUB_*``, ``OPENAI_*``, ``FORGE_*``).
* Explicitly absent (LLD §58, real sandbox later): CPU/memory limits,
  namespaces/cgroups, filesystem isolation beyond the workspace dir,
  and network policy.

Constraint: execute only trusted fixture code in Phase 2. The Docker
sandbox later implements the same ``SandboxExecutor`` interface.

Shared venv: built ONCE from the fixture's pinned requirements (see
``fixtures/todo-app/README.md``) and passed as
``ExecutorConfig.venv_path``. Its ``bin/`` is prepended to ``PATH``
for ``run_command``; no ``pip`` ever runs inside the loop.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import os
import re
import shutil
import time
import uuid
from asyncio.subprocess import PIPE
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self, TypeVar

from forge_worker.sandbox.errors import (
    BINARY_FILE,
    COMMAND_NOT_ALLOWED,
    EDIT_AMBIGUOUS,
    EDIT_NO_MATCH,
    FILE_NOT_FOUND,
    FILE_TOO_LARGE,
    GIT_OPERATION_FAILED,
    INVALID_INPUT,
    INVALID_RUN_ID,
    PATH_OUTSIDE_WORKSPACE,
    PROTECTED_PATH,
    SANDBOX_TIMEOUT,
    TOOL_EXECUTION_FAILED,
    WORKSPACE_EXISTS,
    ToolError,
)
from forge_worker.sandbox.protocols import (
    CommandResult,
    EditResult,
    FileContent,
    FileMatch,
    GitStatus,
    ToolCallRecord,
    ToolCallStore,
    WriteResult,
)
from forge_worker.sandbox.store import InMemoryToolCallStore

T = TypeVar("T")

_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

_SCRUB_EXACT = frozenset({"DATABASE_URL"})
_SCRUB_PREFIXES = ("GITHUB_", "OPENAI_", "FORGE_")


@dataclass(frozen=True)
class ExecutorConfig:
    """Tuning knobs for :class:`LocalWorkspaceExecutor`."""

    run_id: str = "run-local"
    venv_path: Path | None = None
    command_timeout_seconds: float = 120.0
    allowed_commands: tuple[str, ...] = ("pytest",)
    max_read_bytes: int = 1_000_000
    max_output_bytes: int = 256_000
    preview_chars: int = 4_000
    max_diff_chars: int = 100_000
    tool_call_store: ToolCallStore | None = None


def sanitize_env(venv_path: Path | None = None) -> dict[str, str]:
    """Copy ``os.environ`` minus secret-bearing keys.

    Drops ``DATABASE_URL`` and any ``GITHUB_*``/``OPENAI_*``/``FORGE_*``
    entries so agent-driven commands never inherit host credentials.
    When ``venv_path`` is set, its ``bin/`` is prepended to ``PATH``
    and ``VIRTUAL_ENV`` is pointed at it.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _SCRUB_EXACT and not key.startswith(_SCRUB_PREFIXES)
    }
    if venv_path is not None:
        env["PATH"] = str(venv_path / "bin") + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv_path)
    return env


def _duration_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _program_of(command: list[str]) -> str:
    """Reduce argv to the allowlisted program name.

    ``python -m pytest`` counts as ``pytest`` so the shared venv's
    interpreter can drive the suite without widening the allowlist.
    """
    prog = Path(command[0]).name
    if (prog == "python" or prog.startswith("python3")) and command[1:2] == ["-m"]:
        return command[2] if len(command) > 2 else prog
    return prog


class LocalWorkspaceExecutor:
    """``SandboxExecutor`` over one workspace directory on local disk."""

    def __init__(self, workspace_path: Path, config: ExecutorConfig | None = None) -> None:
        self._workspace = workspace_path
        self._root = workspace_path.resolve()
        self._config = config or ExecutorConfig()
        self._store = self._config.tool_call_store or InMemoryToolCallStore()
        self._command_counter = 0

    @classmethod
    async def create(
        cls,
        workspace_root: Path,
        run_id: str,
        fixture_dir: Path,
        config: ExecutorConfig | None = None,
    ) -> Self:
        """Seed a per-run workspace: copy fixture in, ``git init``, seed commit."""
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ToolError(INVALID_RUN_ID, f"invalid run id: {run_id!r}")
        dest = workspace_root / run_id
        if dest.exists():
            raise ToolError(WORKSPACE_EXISTS, f"workspace exists: {dest}")
        shutil.copytree(
            fixture_dir,
            dest,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc", ".venv"),
        )
        executor = cls(dest, config or ExecutorConfig(run_id=run_id))
        await executor._git("init", "-b", "main")
        await executor._git("add", "-A")
        await executor._git(
            "-c",
            "user.name=forge",
            "-c",
            "user.email=forge@localhost",
            "commit",
            "-m",
            "seed: fixture snapshot",
        )
        return executor

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    @property
    def config(self) -> ExecutorConfig:
        return self._config

    @property
    def tool_calls(self) -> list[ToolCallRecord]:
        """All ToolCall records for this executor's run id."""
        return self._store.list_for_run(self._config.run_id)

    async def _record(self, tool_name: str, call: Callable[[], Awaitable[T]]) -> T:
        """Validate → execute → persist (TOOL_CONTRACTS §10)."""
        start = time.perf_counter()
        run_id = self._config.run_id
        workspace_id = self._workspace.name
        try:
            result = await call()
        except ToolError as exc:
            self._store.save(
                ToolCallRecord(
                    id=uuid.uuid4().hex,
                    tool_name=tool_name,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    status="FAILED",
                    duration_ms=_duration_ms(start),
                    error_code=exc.code,
                )
            )
            raise
        except Exception as exc:
            self._store.save(
                ToolCallRecord(
                    id=uuid.uuid4().hex,
                    tool_name=tool_name,
                    run_id=run_id,
                    workspace_id=workspace_id,
                    status="FAILED",
                    duration_ms=_duration_ms(start),
                    error_code=TOOL_EXECUTION_FAILED,
                )
            )
            raise ToolError(TOOL_EXECUTION_FAILED, f"{tool_name} failed: {exc}") from exc
        self._store.save(
            ToolCallRecord(
                id=uuid.uuid4().hex,
                tool_name=tool_name,
                run_id=run_id,
                workspace_id=workspace_id,
                status="SUCCESS",
                duration_ms=_duration_ms(start),
                error_code=None,
            )
        )
        return result

    def _resolve(self, path: str) -> Path:
        """Resolve ``path`` inside the workspace or reject the traversal."""
        candidate = (self._workspace / path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ToolError(PATH_OUTSIDE_WORKSPACE, f"path escapes workspace: {path!r}")
        return candidate

    def _relative(self, target: Path) -> str:
        return target.relative_to(self._root).as_posix()

    def _ensure_not_protected(self, target: Path, path: str) -> None:
        git_dir = self._root / ".git"
        if target == git_dir or git_dir in target.parents:
            raise ToolError(PROTECTED_PATH, f"protected path: {path!r}")

    def _read_text(self, target: Path, path: str) -> str:
        if not target.is_file():
            raise ToolError(FILE_NOT_FOUND, f"file not found: {path!r}")
        if target.stat().st_size > self._config.max_read_bytes:
            raise ToolError(FILE_TOO_LARGE, f"file too large: {path!r}")
        raw = target.read_bytes()
        if b"\x00" in raw:
            raise ToolError(BINARY_FILE, f"binary file: {path!r}")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolError(BINARY_FILE, f"binary file: {path!r}") from None

    # -- file tools (blocking I/O runs off the loop via to_thread) --

    async def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> FileContent:
        return await self._record(
            "read_file",
            lambda: asyncio.to_thread(self._read_file_sync, path, start_line, end_line),
        )

    def _read_file_sync(self, path: str, start_line: int, end_line: int) -> FileContent:
        if start_line < 1 or end_line < start_line:
            raise ToolError(INVALID_INPUT, f"invalid line range: {start_line}-{end_line}")
        target = self._resolve(path)
        lines = self._read_text(target, path).splitlines()
        selected = lines[start_line - 1 : end_line]
        content = "\n".join(selected) + ("\n" if selected else "")
        return FileContent(
            path=self._relative(target),
            content=content,
            start_line=start_line,
            end_line=start_line + len(selected) - 1 if selected else start_line,
        )

    async def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        return await self._record(
            "list_files",
            lambda: asyncio.to_thread(self._list_files_sync, path, pattern),
        )

    def _list_files_sync(self, path: str, pattern: str) -> list[str]:
        base = self._resolve(path)
        if not base.is_dir():
            raise ToolError(FILE_NOT_FOUND, f"directory not found: {path!r}")
        return sorted(
            self._relative(p) for p in base.rglob(pattern) if p.is_file() and ".git" not in p.parts
        )

    async def search_code(
        self, query: str, path: str = ".", max_results: int = 50
    ) -> list[FileMatch]:
        return await self._record(
            "search_code",
            lambda: asyncio.to_thread(self._search_code_sync, query, path, max_results),
        )

    def _search_code_sync(self, query: str, path: str, max_results: int) -> list[FileMatch]:
        if not query:
            raise ToolError(INVALID_INPUT, "query must not be empty")
        if max_results < 1:
            raise ToolError(INVALID_INPUT, "max_results must be >= 1")
        base = self._resolve(path)
        if not base.is_dir():
            raise ToolError(FILE_NOT_FOUND, f"directory not found: {path!r}")
        matches: list[FileMatch] = []
        for file in sorted(base.rglob("*")):
            if not file.is_file() or ".git" in file.parts:
                continue
            if file.stat().st_size > self._config.max_read_bytes:
                continue
            try:
                raw = file.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append(
                        FileMatch(
                            path=self._relative(file),
                            line=lineno,
                            snippet=line.strip()[:200],
                        )
                    )
                    if len(matches) >= max_results:
                        return matches
        return matches

    async def write_file(self, path: str, content: str) -> WriteResult:
        return await self._record(
            "write_file",
            lambda: asyncio.to_thread(self._write_file_sync, path, content),
        )

    def _write_file_sync(self, path: str, content: str) -> WriteResult:
        target = self._resolve(path)
        self._ensure_not_protected(target, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        return WriteResult(
            path=self._relative(target),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            bytes_written=len(data),
        )

    async def edit_file(self, path: str, old_text: str, new_text: str) -> EditResult:
        return await self._record(
            "edit_file",
            lambda: asyncio.to_thread(self._edit_file_sync, path, old_text, new_text),
        )

    def _edit_file_sync(self, path: str, old_text: str, new_text: str) -> EditResult:
        if not old_text:
            raise ToolError(INVALID_INPUT, "old_text must not be empty")
        target = self._resolve(path)
        self._ensure_not_protected(target, path)
        before = self._read_text(target, path)
        occurrences = before.count(old_text)
        if occurrences == 0:
            raise ToolError(EDIT_NO_MATCH, f"old_text not found in {path!r}")
        if occurrences > 1:
            raise ToolError(EDIT_AMBIGUOUS, f"old_text matches {occurrences}x in {path!r}")
        after = before.replace(old_text, new_text, 1)
        target.write_bytes(after.encode("utf-8"))
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{self._relative(target)}",
                tofile=f"b/{self._relative(target)}",
            )
        )
        return EditResult(path=self._relative(target), diff=diff)

    # -- shell tool --

    async def run_command(
        self,
        command: list[str],
        cwd: str = ".",
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        return await self._record(
            "run_command",
            lambda: self._run_command(command, cwd, timeout_seconds),
        )

    async def _run_command(
        self, command: list[str], cwd: str, timeout_seconds: float | None
    ) -> CommandResult:
        if not command:
            raise ToolError(COMMAND_NOT_ALLOWED, "empty command")
        program = _program_of(command)
        if program not in self._config.allowed_commands:
            raise ToolError(COMMAND_NOT_ALLOWED, f"command not in allowlist: {program!r}")
        workdir = self._resolve(cwd)
        if not workdir.is_dir():
            raise ToolError(FILE_NOT_FOUND, f"cwd not found: {cwd!r}")
        timeout = (
            self._config.command_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if timeout <= 0:
            raise ToolError(INVALID_INPUT, "timeout_seconds must be > 0")
        env = sanitize_env(self._config.venv_path)
        self._command_counter += 1
        artifacts = self._workspace.parent / ".artifacts" / self._workspace.name
        artifacts.mkdir(parents=True, exist_ok=True)
        tag = f"run_command-{self._command_counter:04d}"
        start = time.perf_counter()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workdir),
                env=env,
                stdout=PIPE,
                stderr=PIPE,
            )
        except FileNotFoundError as exc:
            raise ToolError(TOOL_EXECUTION_FAILED, f"executable not found: {command[0]!r}") from exc
        except OSError as exc:
            raise ToolError(TOOL_EXECUTION_FAILED, str(exc)) from exc
        try:
            async with asyncio.timeout(timeout):
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            proc.kill()
            try:
                async with asyncio.timeout(5):
                    await proc.wait()
            except TimeoutError:
                pass
            raise ToolError(SANDBOX_TIMEOUT, f"command exceeded {timeout:g}s timeout") from None
        duration_ms = _duration_ms(start)
        limit = self._config.max_output_bytes
        truncated = len(stdout) > limit or len(stderr) > limit
        stdout_artifact = artifacts / f"{tag}-stdout.log"
        stderr_artifact = artifacts / f"{tag}-stderr.log"
        stdout_artifact.write_bytes(stdout[:limit])
        stderr_artifact.write_bytes(stderr[:limit])
        preview_chars = self._config.preview_chars
        return CommandResult(
            exit_code=proc.returncode if proc.returncode is not None else -1,
            stdout_artifact=stdout_artifact,
            stderr_artifact=stderr_artifact,
            duration_ms=duration_ms,
            stdout_preview=stdout.decode("utf-8", errors="replace")[:preview_chars],
            stderr_preview=stderr.decode("utf-8", errors="replace")[:preview_chars],
            truncated=truncated,
        )

    # -- git tools (workspace-local; identity pinned per command) --

    async def _git(self, *args: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=str(self._root),
                env=sanitize_env(self._config.venv_path),
                stdout=PIPE,
                stderr=PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            raise ToolError(GIT_OPERATION_FAILED, f"git executable unavailable: {exc}") from exc
        try:
            async with asyncio.timeout(self._config.command_timeout_seconds):
                stdout, stderr = await proc.communicate()
        except TimeoutError:
            proc.kill()
            raise ToolError(SANDBOX_TIMEOUT, "git command timed out") from None
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ToolError(
                GIT_OPERATION_FAILED,
                detail or f"git exited with code {proc.returncode}",
            )
        return stdout.decode("utf-8", errors="replace")

    async def git_status(self) -> GitStatus:
        return await self._record("git_status", self._git_status)

    async def _git_status(self) -> GitStatus:
        branch = (await self._git("branch", "--show-current")).strip() or "HEAD"
        porcelain = await self._git("status", "--porcelain=v1", "--untracked-files=all")
        changed = tuple(sorted(line[3:] for line in porcelain.splitlines() if line.strip()))
        return GitStatus(branch=branch, changed_files=changed)

    async def git_diff(self) -> str:
        return await self._record("git_diff", self._git_diff)

    async def _git_diff(self) -> str:
        diff = await self._git("diff", "HEAD", "--")
        limit = self._config.max_diff_chars
        if len(diff) > limit:
            return diff[:limit] + "\n[forge: diff truncated]"
        return diff

    async def git_create_branch(self, branch: str) -> str:
        return await self._record("git_create_branch", lambda: self._git_create_branch(branch))

    async def _git_create_branch(self, branch: str) -> str:
        if (
            not _BRANCH_RE.fullmatch(branch)
            or ".." in branch
            or "/." in branch
            or branch.endswith((".", ".lock", "/"))
        ):
            raise ToolError(INVALID_INPUT, f"invalid branch name: {branch!r}")
        await self._git("checkout", "-b", branch)
        return branch

    async def git_commit(self, message: str) -> str:
        return await self._record("git_commit", lambda: self._git_commit(message))

    async def _git_commit(self, message: str) -> str:
        if not message.strip():
            raise ToolError(INVALID_INPUT, "commit message must not be empty")
        await self._git("add", "-A")
        await self._git(
            "-c",
            "user.name=forge",
            "-c",
            "user.email=forge@localhost",
            "commit",
            "-m",
            message,
        )
        return (await self._git("rev-parse", "HEAD")).strip()


__all__ = ["ExecutorConfig", "LocalWorkspaceExecutor", "sanitize_env"]
