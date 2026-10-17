"""Repo-connect + PR publication (Phase 4, Issue #018).

* :func:`connect_repo` links a project to a GitHub repository (URL
  validated, PAT stored encrypted, opaque ref recorded).
* :func:`publish_pull_request` pushes the task branch and opens the PR.
  It runs post-review-APPROVED at COMPLETED entry via the publisher
  agent; it never transitions the run (terminal runs cannot escalate,
  so failures land on the ``pull_requests`` row with redacted errors
  instead of NEEDS_HUMAN).

Owns no transaction; callers commit. All GitHub tokens stay in-memory
inside this module's calls.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.service import get_implementation, get_plan, get_review, get_test_result
from app.auth.errors import NoGitHubCredentialError
from app.auth.tokens import TokenCipher
from app.core.logging import get_logger
from app.github.client import GitHubAPIClient
from app.github.credentials import resolve_credential, store_credential
from app.github.errors import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
    GitOperationError,
    InvalidRepoConfigError,
)
from app.github.models import PullRequest
from app.github.repos import (
    head_commit,
    is_auth_failure,
    parse_repo_url,
    push_branch,
)
from app.projects.models import Project
from app.projects.service import get_project
from app.runs.enums import RunState
from app.runs.service import get_run

log = get_logger(__name__)

_PR_BODY_LIMIT = 8_000
_RETRY_DELAYS = (1.0, 2.0, 4.0)


async def connect_repo(
    session: AsyncSession,
    *,
    project: Project,
    repo_url: str,
    default_branch: str = "main",
    credential: str,
    cipher: TokenCipher,
) -> Project:
    """Link ``project`` to a GitHub repo (validates + stores the PAT).

    Raises :class:`InvalidRepoURLError` on bad URLs and
    :class:`ValueError` on empty branch/credential. The PAT is stored
    encrypted; only the opaque ref lands on the project.
    """
    parse_repo_url(repo_url)  # validate before mutating anything
    branch = (default_branch or "").strip()
    if not branch:
        raise InvalidRepoConfigError("default_branch must be a non-empty string")
    if not credential or not credential.strip():
        raise InvalidRepoConfigError("credential must be a non-empty string")
    ref = await store_credential(
        session,
        user_id=project.owner_id,
        token_encrypted=cipher.encrypt(credential.strip()),
    )
    project.repo_url = repo_url.strip()
    project.default_branch = branch
    project.github_credential_ref = ref
    project.updated_at = datetime.now(UTC)
    await session.flush()
    return project


async def get_pull_request(session: AsyncSession, run_id: uuid.UUID) -> PullRequest | None:
    """Return the publication row for ``run_id``, if any."""
    result = await session.execute(select(PullRequest).where(PullRequest.run_id == run_id))
    return result.scalar_one_or_none()


async def _upsert_pull_request(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    project_id: uuid.UUID,
    head_branch: str,
    base_commit: str | None,
    status: str,
    pr_number: int | None = None,
    pr_url: str | None = None,
    error_redacted: str | None = None,
) -> PullRequest:
    now = datetime.now(UTC)
    row = await get_pull_request(session, run_id)
    if row is None:
        row = PullRequest(
            run_id=run_id,
            project_id=project_id,
            head_branch=head_branch,
            base_commit=base_commit,
            status=status,
            pr_number=pr_number,
            pr_url=pr_url,
            error_redacted=error_redacted,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.status = status
        row.pr_number = pr_number
        row.pr_url = pr_url
        row.error_redacted = error_redacted
        row.updated_at = now
    await session.flush()
    return row


def build_pr_body(
    *,
    task: str,
    branch: str,
    base_commit: str | None,
    head_commit_sha: str | None,
    plan: dict[str, Any] | None,
    test_result: dict[str, Any] | None,
    implementation: dict[str, Any] | None,
) -> str:
    """Render the PR description (capped; inbound text never trusted)."""
    lines = [f"Forge run for: {task}", "", f"Branch: `{branch}`"]
    if base_commit:
        lines.append(f"Base: `{base_commit[:12]}`")
    if head_commit_sha:
        lines.append(f"Head: `{head_commit_sha[:12]}`")
    if implementation and implementation.get("summary"):
        lines += ["", "## Summary", str(implementation["summary"])]
    if plan:
        lines += ["", "## Plan", str(plan.get("goal", ""))]
    if test_result:
        lines += [
            "",
            "## Tests",
            f"{test_result.get('passed', '?')} passed, {test_result.get('failed', '?')} failed.",
        ]
    if implementation:
        files = implementation.get("files_changed") or []
        if files:
            lines += ["", "## Files", *[f"- `{f}`" for f in files[:50]]]
    body = "\n".join(lines)
    if len(body) > _PR_BODY_LIMIT:
        body = body[:_PR_BODY_LIMIT] + "\n\n[forge: body truncated]"
    return body


def build_pr_title(*, task: str, run_id: uuid.UUID) -> str:
    """``<task> (forge run <short>)``."""
    return f"{task[:80]} (forge run {str(run_id)[:8]})"


def _redacted_error(message: str) -> str:
    return message.strip()[:300]


async def _reconcile(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    project: Project,
    branch: str,
    base_commit: str | None,
    github_client: GitHubAPIClient,
    cipher: TokenCipher,
) -> PullRequest | None:
    """Return the existing PR for ``owner:branch`` as PUBLISHED, if any."""
    owner, repo = parse_repo_url(project.repo_url or "")
    credential = await resolve_credential(
        session, ref=project.github_credential_ref or "", cipher=cipher
    )
    found = await github_client.list_pulls(
        credential=credential,
        owner_repo=f"{owner}/{repo}",
        head=f"{owner}:{branch}",
    )
    if not found:
        return None
    return await _upsert_pull_request(
        session,
        run_id=run_id,
        project_id=project.id,
        head_branch=branch,
        base_commit=base_commit,
        status="PUBLISHED",
        pr_number=found[0].number,
        pr_url=found[0].url,
    )


async def _attempt_publish(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    project: Project,
    branch: str,
    base_commit: str | None,
    workspace_root: Path,
    github_client: GitHubAPIClient,
    cipher: TokenCipher,
) -> PullRequest:
    """One push + open attempt (no retry). Raises typed errors."""
    assert project.repo_url is not None and project.github_credential_ref is not None
    reconciled = await _reconcile(
        session,
        run_id=run_id,
        project=project,
        branch=branch,
        base_commit=base_commit,
        github_client=github_client,
        cipher=cipher,
    )
    if reconciled is not None:
        return reconciled
    owner, repo = parse_repo_url(project.repo_url)
    owner_repo = f"{owner}/{repo}"
    credential = await resolve_credential(session, ref=project.github_credential_ref, cipher=cipher)
    repo_dir = workspace_root / str(run_id)
    if not repo_dir.is_dir():
        raise GitOperationError(f"workspace missing for run {run_id}")
    try:
        await push_branch(
            repo_dir=repo_dir,
            branch=branch,
            default_branch=project.default_branch,
            credential=credential,
        )
    except GitOperationError as exc:
        if is_auth_failure(exc):
            raise GitHubAuthError("GitHub rejected the credential.") from exc
        raise
    head_sha: str | None = None
    try:
        head_sha = await head_commit(repo_dir=repo_dir, credential=credential)
    except GitOperationError:
        head_sha = None
    plan_row = await get_plan(session, run_id)
    test_row = await get_test_result(session, run_id)
    impl_row = await get_implementation(session, run_id)
    run = await get_run(session, run_id)
    opened = await github_client.create_pull(
        credential=credential,
        owner_repo=owner_repo,
        head=branch,
        base=project.default_branch,
        title=build_pr_title(task=run.task, run_id=run_id),
        body=build_pr_body(
            task=run.task,
            branch=branch,
            base_commit=base_commit,
            head_commit_sha=head_sha,
            plan=dict(plan_row.plan) if plan_row is not None else None,
            test_result=dict(test_row.result) if test_row is not None else None,
            implementation=dict(impl_row.result) if impl_row is not None else None,
        ),
    )
    return await _upsert_pull_request(
        session,
        run_id=run_id,
        project_id=project.id,
        head_branch=branch,
        base_commit=base_commit,
        status="PUBLISHED",
        pr_number=opened.number,
        pr_url=opened.url,
    )


async def publish_pull_request(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    workspace_root: Path,
    github_client: GitHubAPIClient,
    cipher: TokenCipher,
) -> PullRequest | None:
    """Push the task branch and open the PR (COMPLETED, APPROVED only).

    Returns the publication row, or ``None`` when there is nothing to
    publish (no project/repo/branch, or review not APPROVED). Failures
    land on a FAILED row and raise the typed error for the caller's
    logs; the run itself is never transitioned (terminal).
    """
    run = await get_run(session, run_id)
    if run.state != RunState.COMPLETED:
        return None
    if run.project_id is None or not run.branch:
        return None
    review_row = await get_review(session, run_id)
    if review_row is None or review_row.review.get("decision") != "APPROVE":
        return None
    project = await get_project(session, run.project_id)
    if not project.repo_url or not project.github_credential_ref:
        return None

    done = await get_pull_request(session, run_id)
    if done is not None and done.status == "PUBLISHED" and done.pr_url:
        return done

    last_error: Exception | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            return await _attempt_publish(
                session,
                run_id=run_id,
                project=project,
                branch=run.branch,
                base_commit=run.base_commit,
                workspace_root=workspace_root,
                github_client=github_client,
                cipher=cipher,
            )
        except GitHubAuthError as exc:
            last_error = exc
            break  # bad credential: retrying cannot help
        except GitHubRateLimitError as exc:
            last_error = exc
        except GitHubAPIError as exc:
            if exc.status_code is None or exc.status_code >= 500 or exc.status_code == 422:
                last_error = exc  # 422 reconciles after the loop
            else:
                raise
        except (GitOperationError, NoGitHubCredentialError) as exc:
            last_error = exc
            break
        if attempt < len(_RETRY_DELAYS):
            await asyncio.sleep(_RETRY_DELAYS[attempt])

    assert last_error is not None
    if isinstance(last_error, GitHubAPIError) and last_error.status_code == 422:
        # Possibly a duplicate-create race: reconcile before failing.
        try:
            reconciled = await _reconcile(
                session,
                run_id=run_id,
                project=project,
                branch=run.branch or "",
                base_commit=run.base_commit,
                github_client=github_client,
                cipher=cipher,
            )
            if reconciled is not None:
                return reconciled
        except Exception as exc:
            log.debug("pr_reconcile_failed", error=str(exc))
    await _upsert_pull_request(
        session,
        run_id=run_id,
        project_id=project.id,
        head_branch=run.branch or "",
        base_commit=run.base_commit,
        status="FAILED",
        error_redacted=_redacted_error(str(last_error)),
    )
    raise last_error


__all__ = [
    "build_pr_body",
    "build_pr_title",
    "connect_repo",
    "get_pull_request",
    "publish_pull_request",
]
