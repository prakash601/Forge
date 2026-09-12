"""Per-run task workspace for the Developer (Issue #008).

Lifecycle: :meth:`WorkspaceManager.ensure` copies the fixture repo into
``root/<run_id>`` and records a seed commit; the Developer then applies
plan-scoped edits through :meth:`Workspace.write_file`,
:meth:`Workspace.edit_file`, and :meth:`Workspace.commit`.

TRUST MODEL — mirrors ``LocalWorkspaceExecutor`` (workers/execution):
path confinement and workspace-local git only. No command execution
lives here; validation commands arrive with the Tester in #009. The
Docker sandbox later replaces this module behind the same idea
(workspace-local edits, recorded diff). Trusted fixture code only.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.agents.errors import WorkspaceError

_RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _resolve(root: Path, rel: str) -> Path:
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkspaceError(f"path escapes workspace: {rel!r}") from exc
    return candidate


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceError(f"git unavailable: {exc}") from exc
    if proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


class Workspace:
    """Confined file + git view over one seeded run directory."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._root = path.resolve()

    @property
    def path(self) -> Path:
        return self._path

    def read_file(self, rel: str, max_chars: int = 20_000) -> str:
        target = _resolve(self._root, rel)
        if not target.is_file():
            raise WorkspaceError(f"file not found: {rel!r}")
        return target.read_text(encoding="utf-8")[:max_chars]

    def write_file(self, rel: str, content: str) -> str:
        """Replace ``rel`` wholesale. Returns the sha256 checksum."""
        target = _resolve(self._root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def edit_file(self, rel: str, old_text: str, new_text: str) -> None:
        """Replace exactly one occurrence of ``old_text`` in ``rel``."""
        target = _resolve(self._root, rel)
        if not target.is_file():
            raise WorkspaceError(f"file not found: {rel!r}")
        current = target.read_text(encoding="utf-8")
        occurrences = current.count(old_text)
        if occurrences == 0:
            raise WorkspaceError(f"edit has no match in {rel!r}")
        if occurrences > 1:
            raise WorkspaceError(f"edit is ambiguous in {rel!r} ({occurrences} matches)")
        target.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")

    def diff(self) -> str:
        return _git(self._root, "diff")

    def commit(self, message: str) -> str:
        if not message or not message.strip():
            raise WorkspaceError("commit message must be non-empty")
        _git(self._root, "add", "-A")
        out = _git(self._root, "commit", "-m", message.strip())
        return out.strip().splitlines()[0] if out.strip() else ""


@dataclass
class WorkspaceManager:
    """Seeds and hands out per-run :class:`Workspace` directories."""

    root: Path
    fixture_dir: Path

    def ensure(self, run_id: str) -> Workspace:
        """Return the workspace for ``run_id``, seeding it if needed."""
        if not _RUN_ID_RE.fullmatch(run_id):
            raise WorkspaceError(f"invalid run id: {run_id!r}")
        if not self.fixture_dir.is_dir():
            raise WorkspaceError(f"fixture repo missing: {self.fixture_dir}")
        dest = self.root / run_id
        if not dest.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.fixture_dir,
                dest,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", ".pytest_cache", "*.pyc", ".venv"
                ),
            )
            workspace = Workspace(dest)
            _git(dest, "init", "-q")
            _git(dest, "add", "-A")
            _git(dest, "commit", "-qm", "seed fixture")
            return workspace
        return Workspace(dest)


__all__ = ["Workspace", "WorkspaceManager"]
