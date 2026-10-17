"""Service tests for tenancy enforcement (Phase 4, Issue #016, DB)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import MemoryCandidate
from app.agents.service import get_latest_memory, save_memory
from app.projects.errors import ProjectNotFoundError
from app.projects.service import (
    create_project,
    get_owned_project,
    list_owned_project_ids,
)
from app.runs.errors import RunNotFoundError
from app.runs.service import create_run, get_owned_run, list_runs
from app.users.service import create_user


async def _owner(session: AsyncSession, email: str = "owner@example.com"):
    return await create_user(session, email=email)


async def _project(session: AsyncSession, owner_id, name: str = "p"):
    return await create_project(session, owner_id=owner_id, name=name)


async def test_get_owned_project(session: AsyncSession) -> None:
    owner = await _owner(session)
    project = await _project(session, owner.id)
    assert (await get_owned_project(session, project.id, owner.id)).id == project.id


async def test_get_owned_project_missing_or_foreign(session: AsyncSession) -> None:
    import uuid as _uuid

    owner = await _owner(session)
    other = await _owner(session, "other@example.com")
    project = await _project(session, owner.id)
    for pid, oid in [
        (_uuid.uuid4(), owner.id),
        (project.id, other.id),
        (project.id, _uuid.uuid4()),
    ]:
        try:
            await get_owned_project(session, pid, oid)
        except ProjectNotFoundError:
            pass
        else:
            raise AssertionError(f"expected ProjectNotFoundError for {pid}/{oid}")


async def test_list_owned_project_ids(session: AsyncSession) -> None:
    owner = await _owner(session)
    other = await _owner(session, "other@example.com")
    mine = await _project(session, owner.id, "mine")
    await _project(session, other.id, "theirs")
    assert await list_owned_project_ids(session, owner.id) == [mine.id]
    assert await list_owned_project_ids(session, other.id) != []


async def test_create_run_with_and_without_project(session: AsyncSession) -> None:
    owner = await _owner(session)
    project = await _project(session, owner.id)
    scoped = await create_run(session, task="scoped", project_id=project.id)
    assert scoped.project_id == project.id
    legacy = await create_run(session, task="legacy")
    assert legacy.project_id is None


async def test_get_owned_run(session: AsyncSession) -> None:
    import uuid as _uuid

    owner = await _owner(session)
    other = await _owner(session, "other@example.com")
    project = await _project(session, owner.id)
    run = await create_run(session, task="t", project_id=project.id)
    assert (await get_owned_run(session, run.id, owner.id)).id == run.id
    for rid, oid in [
        (_uuid.uuid4(), owner.id),
        (run.id, other.id),
        (run.id, _uuid.uuid4()),
    ]:
        try:
            await get_owned_run(session, rid, oid)
        except (RunNotFoundError, ProjectNotFoundError):
            pass
        else:
            raise AssertionError(f"expected not-found for {rid}/{oid}")


async def test_get_owned_run_rejects_legacy_null(session: AsyncSession) -> None:
    owner = await _owner(session)
    run = await create_run(session, task="legacy")
    try:
        await get_owned_run(session, run.id, owner.id)
    except RunNotFoundError:
        pass
    else:
        raise AssertionError("expected RunNotFoundError for legacy NULL run")


async def test_list_runs_scoping(session: AsyncSession) -> None:
    owner = await _owner(session)
    other = await _owner(session, "other@example.com")
    mine = await _project(session, owner.id)
    theirs = await _project(session, other.id)
    await create_run(session, task="m1", project_id=mine.id)
    await create_run(session, task="m2", project_id=mine.id)
    await create_run(session, task="t1", project_id=theirs.id)
    await create_run(session, task="legacy")
    mine_ids = await list_owned_project_ids(session, owner.id)
    runs, total = await list_runs(session, project_ids=mine_ids)
    assert total == 2
    assert {r.task for r in runs} == {"m1", "m2"}
    empty, total_empty = await list_runs(session, project_ids=[])
    assert (empty, total_empty) == ([], 0)
    _all_runs, total_all = await list_runs(session)
    assert total_all == 4


async def test_latest_memory_scoped_to_project(session: AsyncSession) -> None:
    owner = await _owner(session)
    other = await _owner(session, "other@example.com")
    mine = await _project(session, owner.id)
    theirs = await _project(session, other.id)
    run_mine = await create_run(session, task="m", project_id=mine.id)
    run_theirs = await create_run(session, task="t", project_id=theirs.id)
    await save_memory(
        session,
        run_id=run_theirs.id,
        candidates=[MemoryCandidate(memory_type="NOTE", content="theirs")],
    )
    await save_memory(
        session,
        run_id=run_mine.id,
        candidates=[MemoryCandidate(memory_type="NOTE", content="mine")],
    )
    row = await get_latest_memory(session, project_id=mine.id)
    assert row is not None
    assert row.candidates[0]["content"] == "mine"
    row = await get_latest_memory(session, project_id=theirs.id)
    assert row is not None
    assert row.candidates[0]["content"] == "theirs"
    lonely = await _project(session, owner.id, "lonely")
    assert await get_latest_memory(session, project_id=lonely.id) is None
