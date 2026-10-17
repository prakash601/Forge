"""Unit tests for repo URL parsing, branch naming, and backend git (no network).

Clone/push run against a local bare repo with the URL validator
monkeypatched (validation itself is unit-tested below without I/O).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from app.github import repos
from app.github.errors import GitOperationError, InvalidRepoURLError
from app.github.repos import (
    clone_repo,
    is_auth_failure,
    parse_repo_url,
    push_branch,
    task_branch_name,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/octocat/hello", ("octocat", "hello")),
        ("https://github.com/octocat/hello.git", ("octocat", "hello")),
        ("https://github.com/o-c_t.1/r_e-p.o2", ("o-c_t.1", "r_e-p.o2")),
        ("  https://github.com/o/r  ", ("o", "r")),
    ],
)
def test_parse_repo_url_valid(url: str, expected: tuple[str, str]) -> None:
    assert parse_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:o/r.git",
        "https://gitlab.com/o/r",
        "https://user:token@github.com/o/r",
        "https://github.com/o",
        "https://github.com/o/r/extra",
        "https://github.com/../r",
        "https://github.com/o/..",
        "https://github.com//r",
        "not-a-url",
        "",
    ],
)
def test_parse_repo_url_rejects(url: str) -> None:
    with pytest.raises(InvalidRepoURLError):
        parse_repo_url(url)


def test_task_branch_name() -> None:
    run_id = uuid.uuid4()
    assert task_branch_name("Add pagination!", run_id) == f"forge/add-pagination-{str(run_id)[:8]}"
    assert task_branch_name("", run_id).startswith("forge/task-")
    assert task_branch_name("CAPS_and spaces", run_id).startswith("forge/caps-and-spaces-")
    long_name = task_branch_name("x" * 100, run_id)
    assert len(long_name.split("/")[1]) <= 30 + 1 + 8


def test_is_auth_failure() -> None:
    assert is_auth_failure(GitOperationError("clone failed: Authentication failed"))
    assert is_auth_failure(GitOperationError("remote: 403 forbidden"))
    assert not is_auth_failure(GitOperationError("Could not resolve host"))


async def _local_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    proc = await asyncio.create_subprocess_exec(
        "git",
        "init",
        "--bare",
        "-q",
        str(remote),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    assert proc.returncode == 0
    seed = tmp_path / "seed"
    proc = await asyncio.create_subprocess_exec(
        "git",
        "init",
        "-q",
        "-b",
        "main",
        str(seed),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    (seed / "README.md").write_text("hi\n")
    for args in (
        ["add", "-A"],
        ["commit", "-qm", "seed"],
        ["remote", "add", "origin", str(remote)],
        ["push", "-q", "origin", "main"],
    ):
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            *args,
            cwd=str(seed),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        assert proc.returncode == 0, args
    return remote


async def test_clone_and_push_local_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = await _local_bare_remote(tmp_path)
    monkeypatch.setattr(repos, "parse_repo_url", lambda url: ("local", "repo"))
    dest = tmp_path / "ws" / "run-1"
    base = await clone_repo(
        repo_url=str(remote),
        dest=dest,
        branch="forge/x-12345678",
        default_branch="main",
        credential="test-credential",
    )
    assert len(base) == 40
    assert (dest / "README.md").is_file()
    (dest / "NEW.md").write_text("new\n")
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "add",
        "-A",
        "commit",
        "-qm",
        "work",
        cwd=str(dest),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    await push_branch(
        repo_dir=dest,
        branch="forge/x-12345678",
        default_branch="main",
        credential="test-credential",
    )
    # Remote now has the branch (proves push, no --force involved).
    proc = await asyncio.create_subprocess_exec(
        "git",
        "ls-remote",
        str(remote),
        "refs/heads/forge/x-12345678",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert b"forge/x-12345678" in out


async def test_push_refuses_default_branch(tmp_path: Path) -> None:
    with pytest.raises(GitOperationError):
        await push_branch(repo_dir=tmp_path, branch="main", default_branch="main", credential="x")
    with pytest.raises(GitOperationError):
        await push_branch(repo_dir=tmp_path, branch="trunk", default_branch="trunk", credential="x")
