"""COMPLETED-entry publisher agent (Phase 4, Issue #018).

Registered for ``RunState.COMPLETED`` so the orchestrator schedules it
when a run terminates. It pushes the task branch and opens the PR for
review-APPROVED, repo-backed runs, then returns ``None`` (no further
transition — the run stays COMPLETED).

Terminal-state safety: this agent never raises to the orchestrator
(which would attempt ``unrecoverable_error`` on a terminal run) and
never transitions. Publication failures land on the ``pull_requests``
row (FAILED, redacted) for the details surface.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TokenCipher
from app.core.logging import get_logger
from app.github.client import GitHubAPIClient
from app.github.errors import GitHubAPIError, GitOperationError
from app.github.service import publish_pull_request
from app.metrics.registry import record_pr_publication
from app.runs.enums import RunState
from app.runs.service import get_run

log = get_logger(__name__)


class PublisherAgent:
    """Publish the change as a GitHub PR when a run completes."""

    name = "publisher"

    def __init__(
        self,
        *,
        session_factory: Callable[[], AsyncSession],
        workspace_root: Path,
        github_client: GitHubAPIClient,
        cipher: TokenCipher | None,
    ) -> None:
        self._session_factory = session_factory
        self._workspace_root = workspace_root
        self._github_client = github_client
        self._cipher = cipher

    async def run(self, context: Any) -> str | None:
        run_id = getattr(context, "run_id", None)
        if run_id is None:
            return None
        request_id = str(getattr(context, "request_id", ""))
        if self._cipher is None:
            record_pr_publication(outcome="skipped")
            log.info(
                "publisher_skipped",
                run_id=str(run_id),
                reason="no_credentials_key",
                request_id=request_id,
            )
            return None
        session = self._session_factory()
        try:
            try:
                run_uuid = run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
                run = await get_run(session, run_uuid)
            except Exception as exc:
                log.info(
                    "publisher_skipped",
                    run_id=str(run_id),
                    reason=f"run_unreadable: {type(exc).__name__}",
                    request_id=request_id,
                )
                return None
            if run.state != RunState.COMPLETED:
                return None
            try:
                row = await publish_pull_request(
                    session,
                    run_id=run.id,
                    workspace_root=self._workspace_root,
                    github_client=self._github_client,
                    cipher=self._cipher,
                )
                await session.commit()
            except (GitHubAPIError, GitOperationError) as exc:
                # FAILED row is already recorded; the run stays COMPLETED.
                await session.rollback()
                record_pr_publication(outcome="failed")
                log.warning(
                    "publisher_failed",
                    run_id=str(run.id),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    request_id=request_id,
                )
                return None
            if row is None:
                record_pr_publication(outcome="skipped")
                log.info(
                    "publisher_skipped",
                    run_id=str(run.id),
                    reason="nothing_to_publish",
                    request_id=request_id,
                )
            else:
                record_pr_publication(outcome="published")
                log.info(
                    "publisher_published",
                    run_id=str(run.id),
                    pr_url=row.pr_url,
                    request_id=request_id,
                )
            return None
        except Exception as exc:  # terminal-state safety net; never escalate
            log.error(
                "publisher_unexpected",
                run_id=str(run_id),
                error_type=type(exc).__name__,
                error_message=str(exc),
                exc_info=True,
                request_id=request_id,
            )
            try:
                await session.rollback()
            except Exception as rollback_exc:
                log.debug("publisher_rollback_failed", error=str(rollback_exc))
            return None
        finally:
            await session.close()


__all__ = ["PublisherAgent"]
