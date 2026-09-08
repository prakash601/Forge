"""End-to-end: seed → pytest → break → pytest(red) → fix → pytest(green).

Everything goes through the ``SandboxExecutor`` interface with the
default ``pytest``-only allowlist; the shared venv (session fixture)
means no ``pip`` runs inside the loop.
"""

from __future__ import annotations

from pathlib import Path

from forge_worker.sandbox import ExecutorConfig, LocalWorkspaceExecutor
from tests.conftest import FIXTURE_DIR


async def _seed(tmp_path: Path, venv_python: Path, run_id: str) -> LocalWorkspaceExecutor:
    return await LocalWorkspaceExecutor.create(
        tmp_path,
        run_id,
        FIXTURE_DIR,
        ExecutorConfig(run_id=run_id, venv_path=venv_python.parent.parent),
    )


async def test_seed_pytest_cycle(tmp_path: Path, todo_venv_python: Path) -> None:
    executor = await _seed(tmp_path, todo_venv_python, "run-e2e")

    # Baseline: fixture suite passes through the interface.
    baseline = await executor.run_command(
        [str(todo_venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    )
    assert baseline.exit_code == 0, baseline.stderr_preview
    assert "13 passed" in baseline.stdout_preview

    # Developer breaks the health endpoint via edit_file...
    await executor.edit_file(
        "app/main.py", 'return {"status": "ok"}', 'return {"status": "broken"}'
    )
    red = await executor.run_command(
        [str(todo_venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    )
    assert red.exit_code != 0  # command ran; the suite failed (tool SUCCESS)
    assert executor.tool_calls[-1].status == "SUCCESS"

    # ...debugger reverts the edit, suite goes green again.
    await executor.edit_file(
        "app/main.py", 'return {"status": "broken"}', 'return {"status": "ok"}'
    )
    green = await executor.run_command(
        [str(todo_venv_python), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    )
    assert green.exit_code == 0, green.stderr_preview

    # Git captures the final change set on a task branch.
    await executor.git_create_branch("forge/e2e-todo")
    await executor.edit_file(
        "app/main.py", 'title="Forge Todo Fixture"', 'title="Forge Todo Fixture v2"'
    )
    diff = await executor.git_diff()
    assert "Forge Todo Fixture v2" in diff
    sha = await executor.git_commit("feat: retitle fixture app")
    assert len(sha) == 40
    status = await executor.git_status()
    assert status.branch == "forge/e2e-todo"
    assert status.changed_files == ()

    # Every step left a ToolCall record.
    tool_names = [record.tool_name for record in executor.tool_calls]
    for expected in (
        "run_command",
        "edit_file",
        "git_create_branch",
        "git_diff",
        "git_commit",
        "git_status",
    ):
        assert expected in tool_names, tool_names


async def test_bare_pytest_resolves_via_shared_venv(tmp_path: Path, todo_venv_python: Path) -> None:
    """The default allowlist entry ``pytest`` works with the venv on PATH."""
    executor = await _seed(tmp_path, todo_venv_python, "run-e2e-bare")
    result = await executor.run_command(
        ["pytest", "-q", "-p", "no:cacheprovider", "tests/test_todos.py::test_health"]
    )
    assert result.exit_code == 0, result.stderr_preview
    assert "1 passed" in result.stdout_preview
