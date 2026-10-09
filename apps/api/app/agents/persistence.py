"""Lifespan persistence for agent callbacks (Issue #85).

The agents take loose ``save_fn`` / ``*_provider`` callbacks; the
implementations below are the fully-typed session-owning halves.
``main.lifespan`` keeps only thin adapters that coerce the ``object``
arguments and delegate here, so every open/commit/rollback/close
sequence lives in one ``_session_scope`` instead of ten closures.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import service as agent_service
from app.agents.schemas import (
    ArchaeologistFindings,
    DebuggerDiagnosis,
    DeveloperResult,
    MemoryCandidate,
    Plan,
    ReviewDecision,
    TestReport,
)
from app.core.logging import get_logger
from app.memory.embeddings.protocols import EmbeddingProvider

log = get_logger(__name__)

#: Sync session maker (``async_sessionmaker``), as opposed to the
#: orchestrator's async ``SessionFactory``.
SessionMaker = Callable[[], AsyncSession]


@asynccontextmanager
async def _session_scope(maker: SessionMaker) -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on success and rolls back on error."""
    session = maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def coerce_run_id(run_id: uuid.UUID | str) -> uuid.UUID:
    """Accept the UUID-or-string the agents hand over."""
    return run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))


async def save_analysis_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    findings: ArchaeologistFindings,
    provider: str,
    model: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_analysis(
            session, run_id=coerce_run_id(run_id), findings=findings, provider=provider, model=model
        )


async def save_plan_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    plan: Plan,
    provider: str,
    model: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_plan(
            session, run_id=coerce_run_id(run_id), plan=plan, provider=provider, model=model
        )


async def save_implementation_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    result: DeveloperResult,
    provider: str,
    model: str,
    workspace_path: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_implementation(
            session,
            run_id=coerce_run_id(run_id),
            result=result,
            provider=provider,
            model=model,
            workspace_path=workspace_path,
        )


async def save_test_result_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    result: TestReport,
    provider: str,
    model: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_test_result(
            session, run_id=coerce_run_id(run_id), result=result, provider=provider, model=model
        )


async def save_diagnosis_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    diagnosis: DebuggerDiagnosis,
    provider: str,
    model: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_diagnosis(
            session,
            run_id=coerce_run_id(run_id),
            diagnosis=diagnosis,
            provider=provider,
            model=model,
        )


async def save_review_record(
    maker: SessionMaker,
    *,
    run_id: uuid.UUID | str,
    review: ReviewDecision,
    provider: str,
    model: str,
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_review(
            session, run_id=coerce_run_id(run_id), review=review, provider=provider, model=model
        )


async def save_memory_record(
    maker: SessionMaker, *, run_id: uuid.UUID | str, candidates: list[MemoryCandidate]
) -> None:
    async with _session_scope(maker) as session:
        await agent_service.save_memory(
            session, run_id=coerce_run_id(run_id), candidates=candidates
        )


async def load_findings(
    maker: SessionMaker, *, run_id: uuid.UUID | str
) -> ArchaeologistFindings | None:
    async with _session_scope(maker) as session:
        row = await agent_service.get_analysis(session, coerce_run_id(run_id))
        return ArchaeologistFindings.model_validate(row.findings) if row is not None else None


async def load_plan(maker: SessionMaker, *, run_id: uuid.UUID | str) -> Plan | None:
    async with _session_scope(maker) as session:
        row = await agent_service.get_plan(session, coerce_run_id(run_id))
        return Plan.model_validate(row.plan) if row is not None else None


async def load_diagnosis(
    maker: SessionMaker, *, run_id: uuid.UUID | str
) -> DebuggerDiagnosis | None:
    async with _session_scope(maker) as session:
        row = await agent_service.get_diagnosis(session, coerce_run_id(run_id))
        return DebuggerDiagnosis.model_validate(row.diagnosis) if row is not None else None


async def load_test_report(maker: SessionMaker, *, run_id: uuid.UUID | str) -> TestReport | None:
    async with _session_scope(maker) as session:
        row = await agent_service.get_test_result(session, coerce_run_id(run_id))
        return TestReport.model_validate(row.result) if row is not None else None


async def load_memory_lines(
    maker: SessionMaker,
    embedding_provider: EmbeddingProvider | None,
    *,
    run_id: uuid.UUID | None,
) -> list[str]:
    """Latest-memory lines plus vector recall for ``run_id``'s project.

    Fail closed: without a run (or a project on it) there is no
    memory — a global fallback would leak one owner's outcomes into
    another's archaeology (#016). Any recall failure degrades to the
    latest-memory lines.
    """
    from app.memory.service import search_similar_memories
    from app.runs.service import get_run

    async with _session_scope(maker) as session:
        if run_id is None:
            return []
        try:
            run = await get_run(session, run_id)
        except Exception:
            return []
        if run.project_id is None:
            return []
        lines: list[str] = []
        row = await agent_service.get_latest_memory(session, project_id=run.project_id)
        if row is not None:
            lines.extend(
                f"{c.get('memory_type', 'NOTE')}: {c.get('content', '')}"
                for c in row.candidates
                if isinstance(c, dict)
            )
        # Vector recall: nearest ACTIVE memories to the task text, so
        # old but relevant learnings surface even when they are not
        # the latest. Same per-project scoping.
        try:
            if embedding_provider is not None and run.task.strip():
                query = await embedding_provider.embed(run.task)
                similar = await search_similar_memories(
                    session,
                    project_id=run.project_id,
                    query_embedding=query,
                    limit=5,
                )
                for item in similar:
                    line = f"{item.memory_type}: {item.content}"
                    if line not in lines:
                        lines.append(line)
        except Exception:
            log.warning("memory_vector_recall_failed", run_id=str(run_id))
        return lines


__all__ = [
    "SessionMaker",
    "coerce_run_id",
    "load_diagnosis",
    "load_findings",
    "load_memory_lines",
    "load_plan",
    "load_test_report",
    "save_analysis_record",
    "save_diagnosis_record",
    "save_implementation_record",
    "save_memory_record",
    "save_plan_record",
    "save_review_record",
    "save_test_result_record",
]
