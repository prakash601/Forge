"""Read-only repo tools for the Archaeologist (TOOL_CONTRACTS §9).

Allowed: read_file, list_files, search_code, git_diff.
Denied: write_file, edit_file, run_command, git_commit, create_pr.
"""

from __future__ import annotations

import fnmatch
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.agents.errors import ToolPermissionError

_MAX_READ_CHARS = 20_000
_MAX_SEARCH_RESULTS = 50


def _resolve(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ToolPermissionError(f"path escapes workspace: {rel!r}") from exc
    return candidate


@dataclass
class ReadOnlyRepoTools:
    """Filesystem-backed read-only tools confined to ``root``."""

    root: Path

    def list_files(self, path: str = ".", pattern: str = "*") -> list[str]:
        base = _resolve(self.root, path)
        if not base.exists():
            return []
        out: list[str] = []
        if base.is_file():
            return [base.relative_to(self.root.resolve()).as_posix()]
        for child in sorted(base.rglob("*")):
            if child.is_file():
                rel = child.relative_to(self.root.resolve()).as_posix()
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(child.name, pattern):
                    out.append(rel)
            if len(out) >= 200:
                break
        return out

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        target = _resolve(self.root, path)
        if not target.is_file():
            raise FileNotFoundError(f"file not found: {path!r}")
        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolPermissionError(f"binary file requires explicit handling: {path!r}") from exc
        lines = text.splitlines()
        start = max(1, start_line) - 1
        end = max(start + 1, end_line)
        return "\n".join(lines[start:end])[:_MAX_READ_CHARS]

    def search_code(
        self, query: str, path: str = ".", max_results: int = 50
    ) -> list[dict[str, object]]:
        base = _resolve(self.root, path)
        matches: list[dict[str, object]] = []
        limit = min(max(1, max_results), _MAX_SEARCH_RESULTS)
        for child in sorted(base.rglob("*")):
            if not child.is_file() or child.suffix in {".pyc"}:
                continue
            if "__pycache__" in child.parts or ".git" in child.parts:
                continue
            try:
                text = child.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    rel = child.relative_to(self.root.resolve()).as_posix()
                    matches.append({"path": rel, "line": lineno, "snippet": line.strip()[:300]})
                    if len(matches) >= limit:
                        return matches
        return matches

    def git_diff(self) -> str:
        try:
            proc = subprocess.run(  # noqa: S603
                ["git", "-C", str(self.root), "diff", "--stat"],  # noqa: S607
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "")[:4000]

    # -- denied writes (TOOL_CONTRACTS §9 permission table) --
    def write_file(self, path: str, content: str) -> object:
        raise ToolPermissionError(f"write_file denied for Archaeologist: {path!r}")

    def edit_file(self, path: str, patch: str) -> object:
        raise ToolPermissionError(f"edit_file denied for Archaeologist: {path!r}")

    def run_command(self, command: str) -> object:
        raise ToolPermissionError(f"run_command denied for Archaeologist: {command!r}")

    def git_commit(self, message: str) -> object:
        raise ToolPermissionError(f"git_commit denied for Archaeologist: {message!r}")


__all__ = ["ReadOnlyRepoTools"]
