"""Tests for the v1.0 approval default (Phase 4, Issue #020)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.policy import ProjectPolicyAgent
from app.projects.service import create_project
from app.runs import service as runs_service
from app.users.service import create_user


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _owner_project_run(
    engine: AsyncEngine,
    *,
    email: str,
    auto_approve_policy: bool,
    with_project: bool = True,
) -> uuid.UUID:
    """Committed owner/project/run triple visible to fresh sessions."""
    maker = _maker(engine)
    async with maker() as session:
        owner = await create_user(session, email=email)
        project_id = None
        if with_project:
            project = await create_project(
                session,
                owner_id=owner.id,
                name="p",
                auto_approve_policy=auto_approve_policy,
            )
            project_id = project.id
        run = await runs_service.create_run(session, task="t", project_id=project_id)
        await session.commit()
        return run.id


def _agent(engine: AsyncEngine, *, global_auto_approve: bool = False) -> ProjectPolicyAgent:
    maker = _maker(engine)
    return ProjectPolicyAgent(session_factory=maker, global_auto_approve=global_auto_approve)


def _ctx(run_id: uuid.UUID) -> Any:
    return SimpleNamespace(run_id=run_id, request_id="req-test")


async def test_config_default_is_human_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import Settings

    monkeypatch.delenv("FORGE_AUTO_APPROVE", raising=False)
    monkeypatch.delenv("auto_approve", raising=False)
    assert Settings().auto_approve is False
    assert Settings(auto_approve=True).auto_approve is True


async def test_global_true_approves_without_db(engine: AsyncEngine) -> None:
    agent = _agent(engine, global_auto_approve=True)
    assert await agent.run(_ctx(uuid.uuid4())) == "plan_approved"


async def test_opted_in_project_approves(engine: AsyncEngine) -> None:
    run_id = await _owner_project_run(engine, email="a@x.com", auto_approve_policy=True)
    assert await _agent(engine).run(_ctx(run_id)) == "plan_approved"


async def test_default_project_waits_for_human(engine: AsyncEngine) -> None:
    run_id = await _owner_project_run(engine, email="b@x.com", auto_approve_policy=False)
    assert await _agent(engine).run(_ctx(run_id)) is None


async def test_legacy_ownerless_run_waits(engine: AsyncEngine) -> None:
    run_id = await _owner_project_run(
        engine, email="c@x.com", auto_approve_policy=True, with_project=False
    )
    assert await _agent(engine).run(_ctx(run_id)) is None


async def test_unknown_or_bad_run_waits(engine: AsyncEngine) -> None:
    agent = _agent(engine)
    assert await agent.run(_ctx(uuid.uuid4())) is None
    assert await agent.run(SimpleNamespace(run_id="not-a-uuid", request_id="r")) is None
    assert await agent.run(SimpleNamespace(request_id="r")) is None


async def test_project_create_flag_roundtrip(authed_client: Any) -> None:
    opted = await authed_client.post(
        "/api/v1/projects", json={"name": "opted", "auto_approve_policy": True}
    )
    assert opted.status_code == 201
    assert opted.json()["auto_approve_policy"] is True
    defaulted = await authed_client.post("/api/v1/projects", json={"name": "plain"})
    assert defaulted.json()["auto_approve_policy"] is False


async def test_policy_agent_actor_is_policy(engine: AsyncEngine) -> None:
    """The audit trail binds policy approvals (CONTEXT.md approved-by actor)."""
    from app.agents.policy import ProjectPolicyAgent

    assert ProjectPolicyAgent.approval_actor == "policy"


async def test_project_patch_opt_in(authed_client: Any) -> None:
    created = await authed_client.post("/api/v1/projects", json={"name": "p"})
    assert created.status_code == 201
    project_id = created.json()["id"]
    patched = await authed_client.patch(
        f"/api/v1/projects/{project_id}", json={"auto_approve_policy": True}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["auto_approve_policy"] is True
    back = await authed_client.patch(
        f"/api/v1/projects/{project_id}", json={"auto_approve_policy": False}
    )
    assert back.json()["auto_approve_policy"] is False


async def test_project_patch_validation(authed_client: Any) -> None:
    import uuid as _uuid

    created = await authed_client.post("/api/v1/projects", json={"name": "p"})
    project_id = created.json()["id"]
    assert (await authed_client.patch(f"/api/v1/projects/{project_id}", json={})).status_code == 422
    assert (
        await authed_client.patch(f"/api/v1/projects/{project_id}", json={"name": ""})
    ).status_code == 422
    assert (
        await authed_client.patch(f"/api/v1/projects/{_uuid.uuid4()}", json={"name": "x"})
    ).status_code == 404


async def test_project_patch_requires_auth(client: Any) -> None:
    import uuid as _uuid

    assert (
        await client.patch(f"/api/v1/projects/{_uuid.uuid4()}", json={"name": "x"})
    ).status_code == 401
