"""Persistence for Archaeologist findings (LLD §§12-15 seam)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import (
    RunAnalysis,
    RunDiagnosis,
    RunImplementation,
    RunMemory,
    RunPlan,
    RunReview,
    RunTestResult,
)
from app.agents.schemas import (
    ArchaeologistFindings,
    DebuggerDiagnosis,
    DeveloperResult,
    MemoryCandidate,
    Plan,
    ReviewDecision,
    TestReport,
)


async def save_analysis(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    findings: ArchaeologistFindings,
    provider: str,
    model: str,
) -> RunAnalysis:
    """Upsert findings for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunAnalysis, run_id)
    payload = findings.model_dump()
    if existing is None:
        row = RunAnalysis(
            run_id=run_id, findings=payload, provider=provider, model=model, created_at=now
        )
        session.add(row)
        await session.flush()
        return row
    existing.findings = payload
    existing.provider = provider
    existing.model = model
    await session.flush()
    return existing


async def get_analysis(session: AsyncSession, run_id: uuid.UUID) -> RunAnalysis | None:
    result = await session.execute(select(RunAnalysis).where(RunAnalysis.run_id == run_id))
    return result.scalars().first()


__all__ = [
    "get_analysis",
    "get_diagnosis",
    "get_implementation",
    "get_latest_memory",
    "get_memory",
    "get_plan",
    "get_review",
    "get_test_result",
    "save_analysis",
    "save_diagnosis",
    "save_implementation",
    "save_memory",
    "save_plan",
    "save_review",
    "save_test_result",
]


async def save_plan(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    plan: Plan,
    provider: str,
    model: str,
) -> RunPlan:
    """Upsert the validated plan for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunPlan, run_id)
    payload = plan.model_dump()
    if existing is None:
        row = RunPlan(run_id=run_id, plan=payload, provider=provider, model=model, created_at=now)
        session.add(row)
        await session.flush()
        return row
    existing.plan = payload
    existing.provider = provider
    existing.model = model
    await session.flush()
    return existing


async def get_plan(session: AsyncSession, run_id: uuid.UUID) -> RunPlan | None:
    result = await session.execute(select(RunPlan).where(RunPlan.run_id == run_id))
    return result.scalars().first()


async def save_implementation(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    result: DeveloperResult,
    provider: str,
    model: str,
    workspace_path: str,
) -> RunImplementation:
    """Upsert the Developer result for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunImplementation, run_id)
    payload = result.model_dump()
    if existing is None:
        row = RunImplementation(
            run_id=run_id,
            result=payload,
            provider=provider,
            model=model,
            workspace_path=workspace_path,
            created_at=now,
        )
        session.add(row)
        await session.flush()
        return row
    existing.result = payload
    existing.provider = provider
    existing.model = model
    existing.workspace_path = workspace_path
    await session.flush()
    return existing


async def get_implementation(session: AsyncSession, run_id: uuid.UUID) -> RunImplementation | None:
    result = await session.execute(
        select(RunImplementation).where(RunImplementation.run_id == run_id)
    )
    return result.scalars().first()


async def save_test_result(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    result: TestReport,
    provider: str,
    model: str,
) -> RunTestResult:
    """Upsert the Tester report for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunTestResult, run_id)
    payload = result.model_dump()
    if existing is None:
        row = RunTestResult(
            run_id=run_id, result=payload, provider=provider, model=model, created_at=now
        )
        session.add(row)
        await session.flush()
        return row
    existing.result = payload
    existing.provider = provider
    existing.model = model
    await session.flush()
    return existing


async def get_test_result(session: AsyncSession, run_id: uuid.UUID) -> RunTestResult | None:
    result = await session.execute(select(RunTestResult).where(RunTestResult.run_id == run_id))
    return result.scalars().first()


async def save_diagnosis(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    diagnosis: DebuggerDiagnosis,
    provider: str,
    model: str,
) -> RunDiagnosis:
    """Upsert the Debugger diagnosis for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunDiagnosis, run_id)
    payload = diagnosis.model_dump()
    if existing is None:
        row = RunDiagnosis(
            run_id=run_id, diagnosis=payload, provider=provider, model=model, created_at=now
        )
        session.add(row)
        await session.flush()
        return row
    existing.diagnosis = payload
    existing.provider = provider
    existing.model = model
    await session.flush()
    return existing


async def get_diagnosis(session: AsyncSession, run_id: uuid.UUID) -> RunDiagnosis | None:
    result = await session.execute(select(RunDiagnosis).where(RunDiagnosis.run_id == run_id))
    return result.scalars().first()


async def save_review(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    review: ReviewDecision,
    provider: str,
    model: str,
) -> RunReview:
    """Upsert the Reviewer decision for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunReview, run_id)
    payload = review.model_dump()
    if existing is None:
        row = RunReview(
            run_id=run_id, review=payload, provider=provider, model=model, created_at=now
        )
        session.add(row)
        await session.flush()
        return row
    existing.review = payload
    existing.provider = provider
    existing.model = model
    await session.flush()
    return existing


async def get_review(session: AsyncSession, run_id: uuid.UUID) -> RunReview | None:
    result = await session.execute(select(RunReview).where(RunReview.run_id == run_id))
    return result.scalars().first()


async def save_memory(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    candidates: list[MemoryCandidate],
) -> RunMemory:
    """Upsert outcome candidates for ``run_id``. Caller owns commit."""
    now = datetime.now(UTC)
    existing = await session.get(RunMemory, run_id)
    payload = [c.model_dump() for c in candidates]
    if existing is None:
        row = RunMemory(run_id=run_id, candidates=payload, created_at=now)
        session.add(row)
        await session.flush()
        return row
    existing.candidates = payload
    await session.flush()
    return existing


async def get_memory(session: AsyncSession, run_id: uuid.UUID) -> RunMemory | None:
    result = await session.execute(select(RunMemory).where(RunMemory.run_id == run_id))
    return result.scalars().first()


async def get_latest_memory(session: AsyncSession) -> RunMemory | None:
    """Most recent outcome candidates across runs (next-run memory)."""
    from sqlalchemy import desc

    result = await session.execute(
        select(RunMemory).order_by(desc(RunMemory.created_at)).limit(1)
    )
    return result.scalars().first()
