"""Service tests for repo-connect + PR publication (Phase 4, Issue #018, DB)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.service import save_plan, save_review, save_test_result
from app.auth.errors import NoGitHubCredentialError
from app.auth.tokens import TokenCipher
from app.github.client import FakeGitHubAPIClient, PullInfo
from app.github.credentials import resolve_credential
from app.github.errors import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
    InvalidRepoURLError,
)
from app.github.repos import task_branch_name
from app.github.service import (
    build_pr_title,
    connect_repo,
    get_pull_request,
    publish_pull_request,
)
from app.projects.service import create_project
from app.runs import service as runs_service
from app.runs.enums import RunState
from app.users.service import create_user

_REPO = "https://github.com/octocat/hello"


def _cipher() -> TokenCipher:
    return TokenCipher(Fernet.generate_key().decode())


async def _owner(session: AsyncSession, email: str = "dev@example.com"):
    return await create_user(session, email=email)


async def _connected_project(
    session: AsyncSession, cipher: TokenCipher, email: str = "dev@example.com"
):
    owner = await _owner(session, email)
    project = await create_project(session, owner_id=owner.id, name="p")
    await connect_repo(
        session,
        project=project,
        repo_url=_REPO,
        default_branch="main",
        credential="ghp_test-pat",
        cipher=cipher,
    )
    await session.commit()
    return owner, project


async def _completed_run(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    task: str = "Do thing",
    branch: str | None = "UNSET",
    approved: bool = True,
):
    from app.agents.schemas import Plan, ReviewDecision, TestReport

    run = await runs_service.create_run(session, task=task, project_id=project_id)
    if branch == "UNSET":
        run.branch = task_branch_name(task, run.id)
        run.base_commit = "abc123" + "0" * 34
    elif branch is not None:
        run.branch = branch
        run.base_commit = "abc123" + "0" * 34
    await session.flush()
    for event in (
        "repository_ready",
        "analysis_complete",
        "plan_ready",
        "plan_approved",
        "implementation_complete",
        "tests_passed",
        "review_passed",
    ):
        await runs_service.transition(session, run.id, event)
    await session.flush()
    review = ReviewDecision(decision="APPROVE" if approved else "REJECT", summary="s", findings=[])
    await save_review(session, run_id=run.id, review=review, provider="f", model="f")
    await save_plan(
        session,
        run_id=run.id,
        plan=Plan(goal="Ship it", approach="a", rollback_strategy="r"),
        provider="f",
        model="f",
    )
    await save_test_result(
        session,
        run_id=run.id,
        result=TestReport(status="PASS", passed=3, failed=0),
        provider="f",
        model="f",
    )
    await session.commit()
    assert run.state == RunState.COMPLETED
    return run


async def _seed_workspace_repo(
    workspace_root: Path, run_id: uuid.UUID, branch: str, remote: Path
) -> Path:
    """Local git repo standing in for the clone (origin = bare remote)."""
    dest = workspace_root / str(run_id)
    dest.mkdir(parents=True)
    cmds: list[list[str]] = [
        ["init", "-q", "-b", branch],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "work",
        ],
        ["remote", "add", "origin", str(remote)],
    ]
    (dest / "NOTE.md").write_text("work\n")
    for args in cmds:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(dest),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _out, err = await proc.communicate()
        assert proc.returncode == 0, (args, err.decode())
    return dest


async def _bare_remote(tmp_path: Path) -> Path:
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
    return remote


async def test_connect_repo_stores_and_resolves(session: AsyncSession) -> None:
    cipher = _cipher()
    _owner, project = await _connected_project(session, cipher)
    assert project.repo_url == _REPO
    assert project.default_branch == "main"
    assert project.github_credential_ref is not None
    assert project.github_credential_ref.startswith("cred:")
    assert (
        await resolve_credential(session, ref=project.github_credential_ref, cipher=cipher)
        == "ghp_test-pat"
    )


async def test_connect_repo_rejects(session: AsyncSession) -> None:
    cipher = _cipher()
    owner = await _owner(session)
    project = await create_project(session, owner_id=owner.id, name="p")
    with pytest.raises(InvalidRepoURLError):
        await connect_repo(
            session,
            project=project,
            repo_url="git@github.com:o/r.git",
            default_branch="main",
            credential="x",
            cipher=cipher,
        )
    with pytest.raises(ValueError):
        await connect_repo(
            session,
            project=project,
            repo_url=_REPO,
            default_branch="  ",
            credential="x",
            cipher=cipher,
        )
    with pytest.raises(ValueError):
        await connect_repo(
            session,
            project=project,
            repo_url=_REPO,
            default_branch="main",
            credential="  ",
            cipher=cipher,
        )


async def test_publish_skips(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client: FakeGitHubAPIClient = FakeGitHubAPIClient()
    owner = await _owner(session)
    naked = await create_project(session, owner_id=owner.id, name="naked")
    # No project at all.
    legacy = await runs_service.create_run(session, task="legacy")
    await session.commit()
    assert (
        await publish_pull_request(
            session,
            run_id=legacy.id,
            workspace_root=tmp_path,
            github_client=client,
            cipher=cipher,
        )
        is None
    )
    # Project without repo.
    run = await runs_service.create_run(session, task="t", project_id=naked.id)
    await session.commit()
    assert (
        await publish_pull_request(
            session,
            run_id=run.id,
            workspace_root=tmp_path,
            github_client=client,
            cipher=cipher,
        )
        is None
    )
    assert client.list_calls == [] and client.create_calls == []


async def test_publish_skips_unapproved(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient()
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id, approved=False)
    assert (
        await publish_pull_request(
            session,
            run_id=run.id,
            workspace_root=tmp_path,
            github_client=client,
            cipher=cipher,
        )
        is None
    )
    assert client.create_calls == []


async def test_publish_happy_path(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(
        created=PullInfo(number=42, url="https://github.com/octocat/hello/pull/42", state="open")
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    assert run.branch is not None
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch, remote)

    row = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    await session.commit()

    assert row is not None
    assert (row.status, row.pr_number) == ("PUBLISHED", 42)
    assert row.pr_url == "https://github.com/octocat/hello/pull/42"
    assert len(client.create_calls) == 1
    call = client.create_calls[0]
    assert call["owner_repo"] == "octocat/hello"
    assert call["head"] == run.branch and call["base"] == "main"
    assert call["title"] == build_pr_title(task="Do thing", run_id=run.id)
    assert "Ship it" in call["body"] and "3 passed, 0 failed" in call["body"]
    stored = await get_pull_request(session, run.id)
    assert stored is not None and stored.pr_number == 42
    # Remote actually received the branch (proves the push).
    proc = await asyncio.create_subprocess_exec(
        "git",
        "ls-remote",
        str(remote),
        f"refs/heads/{run.branch}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert run.branch.encode() in out


async def test_publish_reconcile_hit_skips_push(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(
        pulls=[PullInfo(number=9, url="https://github.com/octocat/hello/pull/9", state="open")]
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    row = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    assert row is not None and row.pr_number == 9
    assert client.create_calls == []
    proc = await asyncio.create_subprocess_exec(
        "git",
        "ls-remote",
        str(remote),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert b"forge/" not in out


async def test_publish_create_422_reconciles(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(
        pulls=[PullInfo(number=11, url="https://github.com/octocat/hello/pull/11", state="open")],
        create_error=GitHubAPIError("taken", status_code=422),
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    row = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    assert row is not None
    assert (row.status, row.pr_number) == ("PUBLISHED", 11)


async def test_publish_auth_failure_records_failed(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(create_error=GitHubAuthError("bad credentials"))
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    with pytest.raises(GitHubAuthError):
        await publish_pull_request(
            session,
            run_id=run.id,
            workspace_root=tmp_path,
            github_client=client,
            cipher=cipher,
        )
    await session.commit()
    row = await get_pull_request(session, run.id)
    assert row is not None and row.status == "FAILED"
    assert row.pr_url is None and row.error_redacted
    # The run itself stays COMPLETED (terminal runs never escalate).
    assert (await runs_service.get_run(session, run.id)).state == RunState.COMPLETED


async def test_publish_rate_limit_retries_then_succeeds(
    session: AsyncSession, tmp_path: Path
) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(
        created=PullInfo(number=5, url="https://github.com/octocat/hello/pull/5", state="open"),
        create_error_sequence=[GitHubRateLimitError("limited"), GitHubRateLimitError("limited")],
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    row = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    assert row is not None and row.pr_number == 5
    assert len(client.create_calls) == 3


async def test_publish_idempotent_second_call(session: AsyncSession, tmp_path: Path) -> None:
    cipher = _cipher()
    client = FakeGitHubAPIClient(
        created=PullInfo(number=6, url="https://github.com/octocat/hello/pull/6", state="open")
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    first = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    await session.commit()
    second = await publish_pull_request(
        session,
        run_id=run.id,
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )
    assert first is not None and second is not None
    assert (first.pr_number, second.pr_number) == (6, 6)
    assert len(client.create_calls) == 1


async def test_publish_missing_credential_fails(session: AsyncSession, tmp_path: Path) -> None:

    cipher = _cipher()
    client = FakeGitHubAPIClient()
    owner = await _owner(session)
    project = await create_project(session, owner_id=owner.id, name="p")
    project.repo_url = _REPO
    project.github_credential_ref = "cred:00000000-0000-0000-0000-000000000000"
    await session.flush()
    run = await _completed_run(session, project.id)

    with pytest.raises(NoGitHubCredentialError):
        await publish_pull_request(
            session,
            run_id=run.id,
            workspace_root=tmp_path,
            github_client=client,
            cipher=cipher,
        )
    await session.commit()
    row = await get_pull_request(session, run.id)
    assert row is not None and row.status == "FAILED"


async def test_build_pr_title() -> None:
    run_id = uuid.uuid4()
    assert build_pr_title(task="Do thing", run_id=run_id) == (
        f"Do thing (forge run {str(run_id)[:8]})"
    )


async def test_publisher_agent_publishes_and_never_transitions(
    session: AsyncSession, tmp_path: Path
) -> None:
    from app.github.publisher import PublisherAgent
    from app.runs.details import get_run_details

    cipher = _cipher()
    client = FakeGitHubAPIClient(
        created=PullInfo(number=77, url="https://github.com/octocat/hello/pull/77", state="open")
    )
    _, project = await _connected_project(session, cipher)
    run = await _completed_run(session, project.id)
    remote = await _bare_remote(tmp_path)
    await _seed_workspace_repo(tmp_path, run.id, run.branch or "b", remote)

    agent = PublisherAgent(
        session_factory=_session_factory_for(session),
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )

    class Ctx:
        run_id = run.id
        request_id = "req-test"

    assert await agent.run(Ctx()) is None
    details = await get_run_details(session, run.id)
    assert details.pull_request is not None
    assert details.pull_request["pr_number"] == 77
    assert (await runs_service.get_run(session, run.id)).state == RunState.COMPLETED


async def test_publisher_agent_skips_without_repo(session: AsyncSession, tmp_path: Path) -> None:
    from app.github.publisher import PublisherAgent

    cipher = _cipher()
    client = FakeGitHubAPIClient()
    owner = await _owner(session)
    project = await create_project(session, owner_id=owner.id, name="plain")
    run = await _completed_run(session, project.id)
    agent = PublisherAgent(
        session_factory=_session_factory_for(session),
        workspace_root=tmp_path,
        github_client=client,
        cipher=cipher,
    )

    class Ctx:
        run_id = run.id
        request_id = "req-test"

    assert await agent.run(Ctx()) is None
    assert client.create_calls == [] and client.list_calls == []


def _session_factory_for(session: AsyncSession):  # type: ignore[no-untyped-def]
    """Wrap one test session as a factory (same-transaction visibility)."""

    def factory() -> AsyncSession:
        return session

    return factory
