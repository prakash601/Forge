"""Composite run read for the dashboard (Issue #010).

Bundles the run, its step history, every Phase 2 store row, and the
approval actor into one response so the UI needs a single fetch per
run (plus the live stream for updates).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.service import (
    get_analysis,
    get_diagnosis,
    get_implementation,
    get_memory,
    get_plan,
    get_review,
    get_test_result,
)
from app.github.service import get_pull_request
from app.runs import service
from app.runs.errors import RunNotFoundError
from app.runs.schemas import RunRead


class RunDetails(BaseModel):
    """Everything the dashboard shows for one run."""

    run: RunRead
    analysis: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    implementation: dict[str, Any] | None = None
    test_result: dict[str, Any] | None = None
    diagnosis: dict[str, Any] | None = None
    review: dict[str, Any] | None = None
    memory_candidates: list[dict[str, Any]] = Field(default_factory=list)
    approved_by: str | None = None
    pull_request: dict[str, Any] | None = Field(
        default=None, description="Publication record, once the PR is opened (or failed)."
    )


async def get_run_details(session: AsyncSession, run_id: uuid.UUID) -> RunDetails:
    """Assemble the composite read. Raises :class:`RunNotFoundError`."""
    run = await service.get_run(session, run_id)
    await session.refresh(run, attribute_names=["steps"])
    analysis = await get_analysis(session, run_id)
    plan = await get_plan(session, run_id)
    implementation = await get_implementation(session, run_id)
    test_result = await get_test_result(session, run_id)
    diagnosis = await get_diagnosis(session, run_id)
    review = await get_review(session, run_id)
    memory = await get_memory(session, run_id)
    approved_by = next(
        (step.approved_by for step in run.steps if step.event == "plan_approved"),
        None,
    )
    pull_request = await get_pull_request(session, run_id)
    return RunDetails(
        run=RunRead.model_validate(run),
        analysis=analysis.findings if analysis else None,
        plan=plan.plan if plan else None,
        implementation=implementation.result if implementation else None,
        test_result=test_result.result if test_result else None,
        diagnosis=diagnosis.diagnosis if diagnosis else None,
        review=review.review if review else None,
        memory_candidates=list(memory.candidates) if memory else [],
        approved_by=approved_by,
        pull_request=(
            {
                "pr_number": pull_request.pr_number,
                "pr_url": pull_request.pr_url,
                "head_branch": pull_request.head_branch,
                "base_commit": pull_request.base_commit,
                "status": pull_request.status,
                "error": pull_request.error_redacted,
            }
            if pull_request is not None
            else None
        ),
    )


__all__ = ["RunDetails", "RunNotFoundError", "get_run_details"]
