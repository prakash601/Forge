"""Executor factory keyed by backend; mirrors the embeddings registry.

Only ``local`` exists in Phase 2. The Docker sandbox later registers
under a new ``kind`` behind the same ``SandboxExecutor`` interface —
callers switch backends without touching tool-call sites.
"""

from __future__ import annotations

from pathlib import Path

from forge_worker.sandbox.local import ExecutorConfig, LocalWorkspaceExecutor
from forge_worker.sandbox.protocols import SandboxExecutor


def get_executor(
    *,
    kind: str = "local",
    workspace_path: Path,
    config: ExecutorConfig | None = None,
) -> SandboxExecutor:
    """Return the executor for ``kind``.

    Raises:
        ValueError: unknown executor kind.
    """
    normalized = kind.strip().lower()
    if normalized == "local":
        return LocalWorkspaceExecutor(workspace_path, config or ExecutorConfig())
    raise ValueError(f"unknown executor kind: {kind!r}")


__all__ = ["get_executor"]
