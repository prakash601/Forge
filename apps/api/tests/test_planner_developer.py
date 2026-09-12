"""Contract tests for the Planner capability and Developer agent (Issue #008)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agents.developer import DeveloperAgent
from app.agents.errors import ArchaeologistError, ToolPermissionError
from app.agents.planner import PlannerAgent
from app.agents.policy import PolicyAutoApproveAgent
from app.agents.schemas import ArchaeologistFindings, Plan
from app.agents.workspace import WorkspaceManager
from app.llm.fake import FakeLLMProvider
from app.orchestrator.context import AgentContext
from app.runs.enums import RunState

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "todo-app"


class _FakeRun:
    def __init__(self, task: str, state: RunState = RunState.PLANNING) -> None:
        self.id = uuid.uuid4()
        self.state = state
        self.task = task
        self.version = 0
        self.created_at = datetime.now(UTC)


def _ctx(task: str, state: RunState = RunState.PLANNING) -> AgentContext:
    return AgentContext(run=_FakeRun(task, state), steps=(), request_id="req_test")  # type: ignore[arg-type]


def _findings() -> ArchaeologistFindings:
    return ArchaeologistFindings(
        summary="Todo fixture; paginate GET /todos.",
        relevant_files=["app/main.py", "tests/test_todos.py"],
        architecture_findings=["GET /todos has no pagination"],
        conventions=["pydantic models"],
        dependencies=["fastapi"],
        risks=["clients relying on full list"],
        recommended_focus=["app/main.py:list_todos"],
    )


def _plan() -> Plan:
    return Plan(
        goal="Add pagination to GET /todos",
        approach="Slice the in-memory list with limit/offset.",
        steps=[],
        files_to_change=["app/main.py"],
        files_to_add=[],
        tests=["fixture tests still pass"],
        risks=["clients relying on full list"],
        rollback_strategy="Revert the edit.",
    )


def _pagination_pair() -> tuple[str, str]:
    src = (FIXTURE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("def list_todos"))
    old = "\n".join(lines[start : start + 2])
    new = (
        "def list_todos(limit: int = 100, offset: int = 0) -> list[Todo]:\n"
        "    items = [_store[key] for key in sorted(_store)]\n"
        "    return items[offset : offset + limit]"
    )
    return old, new


def _planner_canned() -> dict[str, dict[str, Any]]:
    plan = _plan()
    return {"planner": plan.model_dump()}


def _developer_canned(
    *, extra_edits: list[dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    old, new = _pagination_pair()
    edits = [{"path": "app/main.py", "mode": "edit", "old_text": old, "new_text": new}]
    edits.extend(extra_edits or [])
    return {
        "developer": {
            "edits": edits,
            "summary": "Paginated list_todos.",
            "implementation_notes": ["limit/offset slice"],
            "validation": ["fixture tests"],
            "remaining_risks": [],
        }
    }


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


async def test_planner_returns_validated_plan() -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, plan: Plan, provider: str, model: str) -> None:
        saved.update(plan=plan, provider=provider, model=model)

    async def _findings_provider(*, run_id: uuid.UUID, **kwargs: Any) -> ArchaeologistFindings:
        return _findings()

    agent = PlannerAgent(
        llm=FakeLLMProvider(agent_type="planner", canned=_planner_canned()),
        repo_root=FIXTURE_ROOT,
        save_fn=_save,
        findings_provider=_findings_provider,
    )
    event = await agent.run(_ctx("add pagination to /todos"))
    assert event == "plan_ready"
    plan = saved["plan"]
    assert isinstance(plan, Plan)
    assert plan.files_to_change == ["app/main.py"]
    assert plan.goal.startswith("Add pagination")
    assert saved["provider"] == "fake"


async def test_planner_malformed_output_raises() -> None:
    agent = PlannerAgent(
        llm=FakeLLMProvider(mode="malformed"), repo_root=FIXTURE_ROOT, save_fn=None
    )
    with pytest.raises(ArchaeologistError):
        await agent.run(_ctx("add pagination to /todos"))


async def test_planner_never_edits_code() -> None:
    before = (FIXTURE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    agent = PlannerAgent(
        llm=FakeLLMProvider(agent_type="planner", canned=_planner_canned()),
        repo_root=FIXTURE_ROOT,
        save_fn=None,
    )
    with pytest.raises(ToolPermissionError):
        agent.tools.write_file("app/main.py", "evil")
    with pytest.raises(ToolPermissionError):
        agent.tools.edit_file("app/main.py", "patch")
    await agent.run(_ctx("add pagination to /todos"))
    assert (FIXTURE_ROOT / "app" / "main.py").read_text(encoding="utf-8") == before


async def test_policy_agent_returns_plan_approved() -> None:
    agent = PolicyAutoApproveAgent()
    assert agent.approval_actor == "policy"
    assert await agent.run(_ctx("anything", RunState.AWAITING_APPROVAL)) == "plan_approved"


# ---------------------------------------------------------------------------
# Developer
# ---------------------------------------------------------------------------


async def test_developer_applies_planned_edit(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, result: Any, **kwargs: Any) -> None:
        saved["result"] = result
        saved["workspace_path"] = kwargs.get("workspace_path")

    async def _plan_provider(*, run_id: uuid.UUID, **kwargs: Any) -> Plan:
        return _plan()

    manager = WorkspaceManager(root=tmp_path / "ws", fixture_dir=FIXTURE_ROOT)
    agent = DeveloperAgent(
        llm=FakeLLMProvider(agent_type="developer", canned=_developer_canned()),
        workspaces=manager,
        save_fn=_save,
        plan_provider=_plan_provider,
    )
    run_id = uuid.uuid4()
    ctx = AgentContext(
        run=_FakeRun("add pagination to /todos", RunState.IMPLEMENTING),
        steps=(),
        request_id="r",
    )
    object.__setattr__(ctx.run, "id", run_id)
    assert await agent.run(ctx) == "implementation_complete"
    result = saved["result"]
    assert result.files_changed == ["app/main.py"]
    assert Path(str(saved["workspace_path"])) == manager.ensure(str(run_id)).path
    ws_path = Path(str(saved["workspace_path"]))
    content = (ws_path / "app" / "main.py").read_text(encoding="utf-8")
    assert "limit: int = 100" in content
    assert "offset" in content
    # Fixture repo itself untouched; only the workspace changed.
    assert "limit: int = 100" not in (FIXTURE_ROOT / "app" / "main.py").read_text(encoding="utf-8")


async def test_developer_skips_out_of_plan_edits(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, result: Any, **kwargs: Any) -> None:
        saved["result"] = result
        saved["workspace_path"] = kwargs.get("workspace_path")

    async def _plan_provider(*, run_id: uuid.UUID, **kwargs: Any) -> Plan:
        return _plan()

    extra = [{"path": "README.md", "mode": "write", "content": "unrelated!"}]
    manager = WorkspaceManager(root=tmp_path / "ws", fixture_dir=FIXTURE_ROOT)
    agent = DeveloperAgent(
        llm=FakeLLMProvider(agent_type="developer", canned=_developer_canned(extra_edits=extra)),
        workspaces=manager,
        save_fn=_save,
        plan_provider=_plan_provider,
    )
    run_id = uuid.uuid4()
    ctx = AgentContext(
        run=_FakeRun("add pagination to /todos", RunState.IMPLEMENTING), steps=(), request_id="r"
    )
    object.__setattr__(ctx.run, "id", run_id)
    assert await agent.run(ctx) == "implementation_complete"
    assert saved["result"].files_changed == ["app/main.py"]
    assert any("README.md" in note for note in saved["result"].implementation_notes)
    ws_path = Path(str(saved["workspace_path"]))
    assert "unrelated!" not in (ws_path / "README.md").read_text(encoding="utf-8")


async def test_developer_without_plan_raises(tmp_path: Path) -> None:
    manager = WorkspaceManager(root=tmp_path / "ws", fixture_dir=FIXTURE_ROOT)
    agent = DeveloperAgent(
        llm=FakeLLMProvider(), workspaces=manager, save_fn=None, plan_provider=None
    )
    with pytest.raises(ArchaeologistError, match="no approved plan"):
        await agent.run(_ctx("add pagination to /todos", RunState.IMPLEMENTING))


async def test_developer_unmatched_edit_fails_after_retry(tmp_path: Path) -> None:
    async def _plan_provider(*, run_id: uuid.UUID, **kwargs: Any) -> Plan:
        return _plan()

    canned = _developer_canned()
    canned["developer"]["edits"][0]["old_text"] = "this text does not exist anywhere"
    manager = WorkspaceManager(root=tmp_path / "ws", fixture_dir=FIXTURE_ROOT)
    agent = DeveloperAgent(
        llm=FakeLLMProvider(agent_type="developer", canned=canned),
        workspaces=manager,
        save_fn=None,
        plan_provider=_plan_provider,
    )
    with pytest.raises(ArchaeologistError):
        await agent.run(_ctx("add pagination to /todos", RunState.IMPLEMENTING))


@pytest.mark.integration
async def test_plan_and_implementation_persistence(session: Any) -> None:
    from app.agents.schemas import DeveloperResult
    from app.agents.service import (
        get_implementation,
        get_plan,
        save_implementation,
        save_plan,
    )
    from app.runs.service import create_run

    run = await create_run(session, task="add pagination to /todos")
    await session.commit()
    await save_plan(session, run_id=run.id, plan=_plan(), provider="fake", model="fake-llm")
    await session.commit()
    row = await get_plan(session, run.id)
    assert row is not None
    assert row.provider == "fake"
    assert row.plan["files_to_change"] == ["app/main.py"]

    outcome = DeveloperResult(
        summary="done",
        files_changed=["app/main.py"],
        implementation_notes=[],
        validation=[],
        remaining_risks=[],
    )
    await save_implementation(
        session,
        run_id=run.id,
        result=outcome,
        provider="fake",
        model="fake-llm",
        workspace_path="test-workspace/run-1",
    )
    await session.commit()
    impl = await get_implementation(session, run.id)
    assert impl is not None
    assert impl.workspace_path == "test-workspace/run-1"
    assert impl.result["files_changed"] == ["app/main.py"]


@pytest.mark.integration
async def test_transition_records_approved_by(session: Any) -> None:
    from app.runs import service

    run = await service.create_run(session, task="approval audit")
    await session.commit()
    for event in ("repository_ready", "analysis_complete", "plan_ready"):
        run = await service.transition(session, run.id, event)
        await session.commit()
    run = await service.transition(session, run.id, "plan_approved", approved_by="policy")
    await session.commit()
    assert run.state.value == "IMPLEMENTING"
    await session.refresh(run, attribute_names=["steps"])
    steps = list(run.steps)
    approved = [s for s in steps if s.event == "plan_approved"]
    assert len(approved) == 1
    assert approved[0].approved_by == "policy"

    with pytest.raises(ValueError, match="approved_by"):
        await service.transition(session, run.id, "implementation_complete", approved_by="human")
    with pytest.raises(ValueError, match="approved_by"):
        await service.transition(session, run.id, "cancel", approved_by="someone")
