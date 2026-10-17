"""Executor factory keyed by backend; mirrors the embeddings registry.

``local`` runs commands as host subprocesses (Phase 2). ``docker``
runs them in ephemeral per-command containers (Phase 4, Issue #017)
— callers switch backends without touching tool-call sites.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from forge_worker.sandbox.docker import DockerExecutorConfig, DockerWorkspaceExecutor
from forge_worker.sandbox.local import ExecutorConfig, LocalWorkspaceExecutor
from forge_worker.sandbox.protocols import SandboxExecutor


def _as_docker_config(config: ExecutorConfig) -> DockerExecutorConfig:
    """Coerce a base config to Docker knobs (container fields defaulted)."""
    if isinstance(config, DockerExecutorConfig):
        return config
    shared = {f.name for f in dataclasses.fields(ExecutorConfig)}
    return DockerExecutorConfig(
        **{name: getattr(config, name) for name in shared},
    )


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
    if normalized == "docker":
        return DockerWorkspaceExecutor(
            workspace_path,
            _as_docker_config(config or DockerExecutorConfig()),
        )
    raise ValueError(f"unknown executor kind: {kind!r}")


__all__ = ["get_executor"]
