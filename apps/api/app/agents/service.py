"""Persistence for Archaeologist findings (LLD §§12-15 seam)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import RunAnalysis, RunImplementation, RunPlan
from app.agents.schemas import ArchaeologistFindings, DeveloperResult, Plan


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
    "get_implementation",
    "get_plan",
    "save_analysis",
    "save_implementation",
    "save_plan",
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
