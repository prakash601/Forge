"""Unit tests for the Docker sandbox executor (daemon mocked, no Docker needed)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from forge_worker.sandbox import (
    DockerExecutorConfig,
    DockerWorkspaceExecutor,
    container_env,
    get_executor,
    workspace_disk_bytes,
)
from forge_worker.sandbox.errors import (
    COMMAND_NOT_ALLOWED,
    SANDBOX_RESOURCE_LIMIT,
    SANDBOX_TIMEOUT,
    TOOL_EXECUTION_FAILED,
    ToolError,
)


class FakeContainer:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        oom: bool = False,
        name: str = "",
    ) -> None:
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._oom = oom
        self.name = name
        self.removed = False
        self.stopped = False
        self.attrs: dict[str, Any] = {"State": {"OOMKilled": False}}

    def wait(self) -> dict[str, Any]:
        return {"StatusCode": self._exit_code}

    def logs(self, *, stdout: bool = True, stderr: bool = True) -> bytes:
        if stdout and not stderr:
            return self._stdout
        if stderr and not stdout:
            return self._stderr
        return self._stdout + self._stderr

    def reload(self) -> None:
        self.attrs = {"State": {"OOMKilled": self._oom}}

    def remove(self, force: bool = False) -> None:
        self.removed = True

    def stop(self, timeout: int = 10) -> None:
        self.stopped = True


class FakeImages:
    def __init__(self, *, present: bool = True) -> None:
        self.present = present
        self.pulled: list[str] = []

    def get(self, name: str) -> object:
        if not self.present:
            raise FakeDockerErrors.ImageNotFound(f"no such image: {name}")
        return object()

    def pull(self, name: str) -> object:
        self.pulled.append(name)
        self.present = True
        return object()


class FakeContainers:
    def __init__(self, client: FakeClient) -> None:
        self._client = client
        self.run_kwargs: dict[str, Any] | None = None
        self.run_args: tuple[Any, ...] | None = None

    def run(self, *args: Any, **kwargs: Any) -> FakeContainer:
        self.run_args = args
        self.run_kwargs = kwargs
        container = self._client.next_container()
        container.name = kwargs.get("name", "")
        self._client.started.append(container)
        return container

    def list(self, *, filters: dict[str, Any] | None = None) -> list[FakeContainer]:
        name = (filters or {}).get("name", "")
        return [c for c in self._client.started if not c.removed and c.name == name]


class FakeClient:
    def __init__(self, *, image_present: bool = True) -> None:
        self.images = FakeImages(present=image_present)
        self.containers = FakeContainers(self)
        self.started: list[FakeContainer] = []
        self._pending: list[FakeContainer] = []

    def queue(self, container: FakeContainer) -> None:
        self._pending.append(container)

    def next_container(self) -> FakeContainer:
        if self._pending:
            return self._pending.pop(0)
        return FakeContainer()


class FakeDockerErrors:
    class DockerException(Exception):
        pass

    class ImageNotFound(Exception):
        pass


def install_fake_docker(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> FakeClient:
    """Route ``import docker`` / ``from docker.errors import ...`` to fakes."""
    errors_mod = types.ModuleType("docker.errors")
    errors_mod.DockerException = FakeDockerErrors.DockerException  # type: ignore[attr-defined]
    errors_mod.ImageNotFound = FakeDockerErrors.ImageNotFound  # type: ignore[attr-defined]
    docker_mod = types.ModuleType("docker")
    docker_mod.from_env = lambda *a, **k: client  # type: ignore[attr-defined]
    docker_mod.errors = errors_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", docker_mod)
    monkeypatch.setitem(sys.modules, "docker.errors", errors_mod)
    return client


def make_docker_executor(
    workspace: Path, client: FakeClient, monkeypatch: pytest.MonkeyPatch, **kwargs: Any
) -> DockerWorkspaceExecutor:
    install_fake_docker(monkeypatch, client)
    workspace.mkdir(parents=True, exist_ok=True)
    config = DockerExecutorConfig(run_id="run-docker-test", **kwargs)
    return DockerWorkspaceExecutor(workspace, config)


async def test_run_command_success_records_limits_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("FORGE_JWT_SECRET", "shh")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-x")
    client = FakeClient()
    client.queue(FakeContainer(exit_code=0, stdout=b"ok\n"))
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)

    result = await ex.run_command(["pytest", "tests", "-q"])

    assert result.exit_code == 0
    assert result.stdout_preview == "ok\n"
    assert result.stdout_artifact.is_file()
    kwargs = client.containers.run_kwargs
    assert kwargs is not None
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["memswap_limit"] == "512m"
    assert kwargs["nano_cpus"] == 1_000_000_000
    assert kwargs["pids_limit"] == 128
    assert kwargs["user"] == "1000:1000"
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["volumes"] == {
        str(ex.workspace_path.resolve()): {"bind": "/workspace", "mode": "rw"}
    }
    assert kwargs["working_dir"] == "/workspace"
    env = kwargs["environment"]
    assert "DATABASE_URL" not in env and "GITHUB_TOKEN" not in env
    assert not any(k.startswith("FORGE_") for k in env)
    assert env["PYTEST_ADDOPTS"] == "-x"
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


async def test_run_command_nonzero_exit_is_successful_tool_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    client.queue(FakeContainer(exit_code=1, stdout=b"F", stderr=b"E"))
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)

    result = await ex.run_command(["pytest", "tests"])

    assert result.exit_code == 1
    assert result.stdout_preview == "F"
    assert result.stderr_preview == "E"


async def test_run_command_rejects_disallowed_before_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)
    with pytest.raises(ToolError) as err:
        await ex.run_command(["rm", "-rf", "/"])
    assert err.value.code == COMMAND_NOT_ALLOWED
    assert client.containers.run_kwargs is None


async def test_run_command_timeout_stops_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SlowContainer(FakeContainer):
        def wait(self) -> dict[str, Any]:
            import time as _time

            _time.sleep(5)
            return {"StatusCode": 0}

    client = FakeClient()
    slow = SlowContainer()
    client.queue(slow)
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)

    with pytest.raises(ToolError) as err:
        await ex.run_command(["pytest", "tests"], timeout_seconds=0.2)
    assert err.value.code == SANDBOX_TIMEOUT
    # Best-effort cleanup stops the orphaned container by name.
    assert slow.stopped
    assert client.containers.run_kwargs is not None
    assert client.containers.run_kwargs["name"].startswith("forge-run-docker-test-")


async def test_run_command_oom_maps_to_resource_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    client.queue(FakeContainer(exit_code=137, oom=True))
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)

    with pytest.raises(ToolError) as err:
        await ex.run_command(["pytest", "tests"])
    assert err.value.code == SANDBOX_RESOURCE_LIMIT


async def test_missing_image_never_pulls_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(image_present=False)
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch)

    with pytest.raises(ToolError) as err:
        await ex.run_command(["pytest", "tests"])
    assert err.value.code == TOOL_EXECUTION_FAILED
    assert client.images.pulled == []


async def test_missing_image_pulls_when_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient(image_present=False)
    client.queue(FakeContainer(exit_code=0, stdout=b"ok"))
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch, pull_policy="always")

    result = await ex.run_command(["pytest", "tests"])
    assert result.exit_code == 0
    assert client.images.pulled == ["forge-sandbox:0.1.0"]


async def test_quota_breach_never_touches_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "big.bin").write_bytes(b"x" * 1024)
    ex = make_docker_executor(tmp_path / "ws", client, monkeypatch, workspace_quota_mb=0)

    with pytest.raises(ToolError) as err:
        await ex.run_command(["pytest", "tests"])
    assert err.value.code == SANDBOX_RESOURCE_LIMIT
    assert client.containers.run_kwargs is None


def test_container_env_is_deny_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "s")
    monkeypatch.setenv("GITHUB_TOKEN", "s")
    monkeypatch.setenv("OPENAI_API_KEY", "s")
    monkeypatch.setenv("FORGE_ANYTHING", "s")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setenv("PYTHONPATH", "/host/paths")
    monkeypatch.setenv("PYTHON_GITHUB_TOKEN", "s")
    monkeypatch.setenv("PYTEST_KEEP", "yes")
    env = container_env()
    for blocked in (
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "FORGE_ANYTHING",
        "AWS_SECRET_ACCESS_KEY",
        "PYTHONPATH",
        "PYTHON_GITHUB_TOKEN",
    ):
        assert blocked not in env
    assert env["PYTEST_KEEP"] == "yes"
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def test_workspace_disk_bytes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "a.txt").write_bytes(b"12345")
    assert workspace_disk_bytes(workspace) == 5


def test_registry_docker_kind(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    ex = get_executor(kind="docker", workspace_path=workspace)
    assert isinstance(ex, DockerWorkspaceExecutor)
    with pytest.raises(ValueError):
        get_executor(kind="gvisor", workspace_path=workspace)


def test_config_from_settings() -> None:
    from forge_worker.config import Settings
    from forge_worker.sandbox.docker import DockerExecutorConfig as Cfg

    settings = Settings(
        sandbox_image="custom:1",
        sandbox_memory_mb=256,
        run_max_seconds=60.0,
        run_max_commands=10,
    )
    config = Cfg.from_settings(settings)
    assert (config.image, config.memory_mb) == ("custom:1", 256)
    assert (settings.run_max_seconds, settings.run_max_commands) == (60.0, 10)
