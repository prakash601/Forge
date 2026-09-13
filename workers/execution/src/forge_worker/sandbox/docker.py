"""Docker-backed per-run workspace executor (Phase 4, Issue #017).

:class:`DockerWorkspaceExecutor` subclasses :class:`LocalWorkspaceExecutor`
and overrides only ``run_command``: file and git tools stay host-side
(path confinement is unchanged), while commands run in an ephemeral
per-command container behind the same ``SandboxExecutor`` interface.

Container contract (decided in #58):

* Image: ``infra/docker/sandbox.Dockerfile`` (python:3.11-slim, pinned
  pytest + fixture deps, non-root ``forge``), digest-pinned in prod,
  ``pull_policy: never`` by default.
* Limits: 1 CPU, 512 MB RAM (no swap), 128 pids, read-only rootfs with
  a 64 MB ``/tmp`` tmpfs, ``1000:1000``, ``cap_drop: ALL``,
  ``no-new-privileges``. Disk quota is enforced host-side (storage
  ``size=`` is driver-dependent) via a ``du`` check before each run.
* Network: ``none`` (default-deny; closes SSRF/metadata egress).
* Env: deny-by-default allowlist (``PATH``/``LANG`` container values
  plus ``PYTHON*``/``PYTEST_*`` passthrough). The host ``.env`` is
  never mounted; ``DATABASE_URL``/``GITHUB_*``/``OPENAI_*``/``FORGE_*``
  never enter the container.
* Timeouts mirror the local executor; OOM kills map to
  ``SANDBOX_RESOURCE_LIMIT``.

Placement note: this executor still runs on the worker host (it talks
to the host daemon). Moving execution off the API host entirely needs
the Phase 5 worker job loop; this slice containerizes in place.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from forge_worker.sandbox.errors import (
    COMMAND_NOT_ALLOWED,
    FILE_NOT_FOUND,
    INVALID_INPUT,
    SANDBOX_RESOURCE_LIMIT,
    SANDBOX_TIMEOUT,
    TOOL_EXECUTION_FAILED,
    ToolError,
)
from forge_worker.sandbox.local import (
    ExecutorConfig,
    LocalWorkspaceExecutor,
    _duration_ms,
    _program_of,
)
from forge_worker.sandbox.protocols import CommandResult

log = structlog.get_logger(__name__)

_CONTAINER_WORKDIR = "/workspace"
_CONTAINER_TMPFS = {"/tmp": "size=64m,mode=1777"}  # noqa: S108 — container tmpfs mount, not host temp

# Deny-by-default container environment. PATH/LANG/HOME and the
# PYTHON* constants below are fixed container-safe values (never
# inherited from the host). Only PYTEST_* passes through from the
# operator env: host PYTHON* values (e.g. PYTHONPATH with host paths,
# or *_TOKEN secrets) must never enter the container.
_CONTAINER_PATH = "/usr/local/bin:/usr/bin:/bin"
_CONTAINER_ENV_BASE = {
    "PATH": _CONTAINER_PATH,
    "LANG": "C.UTF-8",
    "HOME": "/tmp",  # noqa: S108 — container HOME on the tmpfs mount, not host temp
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
}
_ENV_PASSTHROUGH_PREFIXES = ("PYTEST_",)


@dataclass(frozen=True)
class DockerExecutorConfig(ExecutorConfig):
    """Container knobs layered over :class:`ExecutorConfig`."""

    image: str = "forge-sandbox:0.1.0"
    cpus: float = 1.0
    memory_mb: int = 512
    pids_limit: int = 128
    workspace_quota_mb: int = 512
    network: str = "none"
    pull_policy: Literal["never", "missing", "always"] = "never"
    container_user: str = "1000:1000"

    @classmethod
    def from_settings(cls, settings: Any) -> DockerExecutorConfig:
        """Build from worker :class:`Settings` (single source of knobs)."""
        return cls(
            image=settings.sandbox_image,
            cpus=settings.sandbox_cpus,
            memory_mb=settings.sandbox_memory_mb,
            pids_limit=settings.sandbox_pids_limit,
            workspace_quota_mb=settings.sandbox_workspace_quota_mb,
            network=settings.sandbox_network,
            pull_policy=settings.sandbox_pull_policy,
        )


def container_env() -> dict[str, str]:
    """Build the deny-by-default container environment."""
    env = dict(_CONTAINER_ENV_BASE)
    for key, value in os.environ.items():
        if key.startswith(_ENV_PASSTHROUGH_PREFIXES):
            env[key] = value
    return env


def workspace_disk_bytes(workspace: Path) -> int:
    """Best-effort ``du`` of the workspace (no symlink following).

    Prefers the ``du -sb`` binary (true block accounting); falls back
    to an apparent-size walk where ``du`` is unavailable. Either way
    this is a pre-run guard, not a live limit: a command that fills
    disk mid-run is caught on the next command (documented TOCTOU).
    """
    import shutil
    import subprocess

    du = shutil.which("du")
    if du is not None:
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                [du, "-sb", "--", str(workspace)],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return int(proc.stdout.split()[0])
        except (OSError, ValueError, IndexError):
            pass
    total = 0
    for root, _dirs, files in os.walk(workspace, followlinks=False):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                continue
    return total


class DockerWorkspaceExecutor(LocalWorkspaceExecutor):
    """``SandboxExecutor`` with containerized ``run_command``."""

    def __init__(self, workspace_path: Path, config: DockerExecutorConfig | None = None) -> None:
        super().__init__(workspace_path, config or DockerExecutorConfig())

    @property
    def docker_config(self) -> DockerExecutorConfig:
        config = self._config
        assert isinstance(config, DockerExecutorConfig)
        return config

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
        self._assert_quota()
        rel = workdir.relative_to(self._root).as_posix()
        container_cwd = f"{_CONTAINER_WORKDIR}/{rel}" if rel != "." else _CONTAINER_WORKDIR
        self._command_counter += 1
        container_name = f"forge-{self._config.run_id}-{self._command_counter:04d}"
        artifacts = self._workspace.parent / ".artifacts" / self._workspace.name
        artifacts.mkdir(parents=True, exist_ok=True)
        tag = f"run_command-{self._command_counter:04d}"
        start = time.perf_counter()
        try:
            async with asyncio.timeout(timeout):
                exit_code, stdout, stderr = await asyncio.to_thread(
                    self._run_container_sync, command, container_cwd, container_name
                )
        except TimeoutError:
            # The worker thread may still be blocked in wait(); stop the
            # container by name so it cannot burn CPU/memory orphaned.
            await asyncio.to_thread(self._best_effort_cleanup, container_name)
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
            exit_code=exit_code,
            stdout_artifact=stdout_artifact,
            stderr_artifact=stderr_artifact,
            duration_ms=duration_ms,
            stdout_preview=stdout.decode("utf-8", errors="replace")[:preview_chars],
            stderr_preview=stderr.decode("utf-8", errors="replace")[:preview_chars],
            truncated=truncated,
        )

    def _assert_quota(self) -> None:
        quota_bytes = self.docker_config.workspace_quota_mb * 1024 * 1024
        used = workspace_disk_bytes(self._root)
        if used > quota_bytes:
            raise ToolError(
                SANDBOX_RESOURCE_LIMIT,
                f"workspace exceeds {self.docker_config.workspace_quota_mb} MB quota",
            )

    def _docker_client(self) -> Any:
        """Build the daemon client (import here so unit tests can stub ``docker``)."""
        try:
            import docker
        except ImportError as exc:
            raise ToolError(
                TOOL_EXECUTION_FAILED,
                "docker package not installed; cannot use the docker executor.",
            ) from exc
        try:
            return docker.from_env()
        except Exception as exc:
            raise ToolError(TOOL_EXECUTION_FAILED, f"docker daemon unavailable: {exc}") from exc

    def _ensure_image(self, client: Any) -> None:
        from docker.errors import ImageNotFound

        cfg = self.docker_config
        try:
            client.images.get(cfg.image)
            found = True
        except ImageNotFound:
            found = False
        if found:
            if cfg.pull_policy == "always":
                client.images.pull(cfg.image)
            return
        if cfg.pull_policy == "never":
            raise ToolError(
                TOOL_EXECUTION_FAILED,
                f"sandbox image {cfg.image!r} not present (pull_policy=never).",
            )
        client.images.pull(cfg.image)

    def _best_effort_cleanup(self, container_name: str) -> None:
        """Stop + remove a possibly-orphaned container by name. Never raises."""
        try:
            import docker
        except ImportError:
            return
        try:
            client = docker.from_env(timeout=5)
            for container in client.containers.list(filters={"name": container_name}):
                try:
                    container.stop(timeout=5)
                except Exception as exc:
                    log.debug("sandbox_cleanup_stop_failed", error=str(exc))
                try:
                    container.remove(force=True)
                except Exception as exc:
                    log.debug("sandbox_cleanup_remove_failed", error=str(exc))
        except Exception as exc:
            log.debug("sandbox_cleanup_failed", error=str(exc))

    def _run_container_sync(
        self, command: list[str], container_cwd: str, container_name: str
    ) -> tuple[int, bytes, bytes]:
        """Run one ephemeral container; returns (exit_code, stdout, stderr).

        Runs in a worker thread (docker-py is blocking). Raises
        :class:`ToolError` with ``SANDBOX_RESOURCE_LIMIT`` on OOM kills.
        """
        from docker.errors import DockerException

        cfg = self.docker_config
        client = self._docker_client()
        try:
            self._ensure_image(client)
        except ToolError:
            raise
        except DockerException as exc:
            raise ToolError(TOOL_EXECUTION_FAILED, f"docker image check failed: {exc}") from exc
        container = None
        try:
            try:
                container = client.containers.run(
                    cfg.image,
                    command,
                    name=container_name,
                    working_dir=container_cwd,
                    environment=container_env(),
                    volumes={str(self._root): {"bind": _CONTAINER_WORKDIR, "mode": "rw"}},
                    network_mode=cfg.network,
                    nano_cpus=int(cfg.cpus * 1_000_000_000),
                    mem_limit=f"{cfg.memory_mb}m",
                    memswap_limit=f"{cfg.memory_mb}m",
                    pids_limit=cfg.pids_limit,
                    read_only=True,
                    tmpfs=_CONTAINER_TMPFS,
                    user=cfg.container_user,
                    cap_drop=["ALL"],
                    security_opt=["no-new-privileges:true"],
                    detach=True,
                )
            except DockerException as exc:
                raise ToolError(TOOL_EXECUTION_FAILED, f"container start failed: {exc}") from exc
            try:
                result = container.wait()
            except DockerException as exc:
                raise ToolError(TOOL_EXECUTION_FAILED, f"container wait failed: {exc}") from exc
            try:
                stdout = container.logs(stdout=True, stderr=False) or b""
                stderr = container.logs(stdout=False, stderr=True) or b""
            except DockerException as exc:
                raise ToolError(TOOL_EXECUTION_FAILED, f"container logs failed: {exc}") from exc
            try:
                container.reload()
                oom_killed = bool(container.attrs.get("State", {}).get("OOMKilled", False))
            except DockerException:
                oom_killed = False
            if oom_killed:
                raise ToolError(
                    SANDBOX_RESOURCE_LIMIT,
                    f"container exceeded {cfg.memory_mb} MB memory limit.",
                )
            status_code = result.get("StatusCode", -1)
            try:
                return int(status_code), bytes(stdout), bytes(stderr)
            except (TypeError, ValueError) as exc:
                raise ToolError(TOOL_EXECUTION_FAILED, f"bad container status: {exc}") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception as exc:
                    log.debug("sandbox_remove_failed", error=str(exc))


__all__ = [
    "DockerExecutorConfig",
    "DockerWorkspaceExecutor",
    "container_env",
    "workspace_disk_bytes",
]
