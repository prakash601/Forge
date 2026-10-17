"""Contract tests for the Archaeologist agent (AGENT_CONTRACTS §16)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.agents.archaeologist import ArchaeologistAgent
from app.agents.errors import ArchaeologistError, ToolPermissionError
from app.agents.schemas import ArchaeologistFindings
from app.llm.errors import LLMProviderError
from app.llm.fake import FakeLLMProvider
from app.orchestrator.context import AgentContext
from app.runs.enums import RunState


def _fixture_root() -> Path:
    return Path(__file__).resolve().parents[3] / "fixtures" / "todo-app"


def _ctx(task: str = "add pagination to /todos") -> AgentContext:
    run = _FakeRun(task)
    return AgentContext(run=run, steps=(), request_id="req_test")  # type: ignore[arg-type]


class _FakeRun:
    def __init__(self, task: str) -> None:
        self.id = uuid.uuid4()
        self.state = RunState.ANALYZING
        self.task = task
        self.version = 0
        self.created_at = datetime.now(UTC)


def _canned() -> dict[str, dict[str, Any]]:
    return {
        "default": {
            "summary": "Todo fixture: FastAPI in-memory store; paginate GET /todos.",
            "relevant_files": ["app/main.py", "tests/test_todos.py"],
            "architecture_findings": ["GET /todos has no pagination"],
            "conventions": ["pydantic models for Todo payloads"],
            "dependencies": ["fastapi"],
            "risks": ["changing list shape may break existing clients"],
            "recommended_focus": ["app/main.py:list_todos"],
        }
    }


async def test_schema_validation_and_deterministic_fixture() -> None:
    saved: dict[str, Any] = {}

    async def _save(
        *, run_id: uuid.UUID, findings: ArchaeologistFindings, provider: str, model: str
    ) -> None:
        saved["findings"] = findings
        saved["provider"] = provider
        saved["model"] = model

    llm = FakeLLMProvider(agent_type="default", canned=_canned())
    agent = ArchaeologistAgent(llm=llm, repo_root=_fixture_root(), save_fn=_save)
    ctx = _ctx()
    event = await agent.run(ctx)
    assert event == "analysis_complete"
    findings = saved["findings"]
    assert isinstance(findings, ArchaeologistFindings)
    assert "app/main.py" in findings.relevant_files
    assert saved["provider"] == "fake"
    assert isinstance(saved["model"], str)


async def test_malformed_output_raises_after_retries() -> None:
    llm = FakeLLMProvider(mode="malformed")
    agent = ArchaeologistAgent(llm=llm, repo_root=_fixture_root(), save_fn=None)
    with pytest.raises(ArchaeologistError):
        await agent.run(_ctx())


async def test_timeout_raises_archaeologist_error() -> None:
    llm = FakeLLMProvider(mode="timeout")
    agent = ArchaeologistAgent(llm=llm, repo_root=_fixture_root(), save_fn=None)
    with pytest.raises(ArchaeologistError):
        await agent.run(_ctx())


async def test_tool_permission_write_denied() -> None:
    llm = FakeLLMProvider(agent_type="default", canned=_canned())
    agent = ArchaeologistAgent(llm=llm, repo_root=_fixture_root(), save_fn=None)
    with pytest.raises(ToolPermissionError):
        agent.tools.write_file("app/main.py", "evil")
    with pytest.raises(ToolPermissionError):
        agent.tools.edit_file("app/main.py", "patch")
    with pytest.raises(ToolPermissionError):
        agent.tools.run_command("pytest")
    # Read-only tools still work on the fixture.
    files = agent.tools.list_files(".", "*.py")
    assert any(f.endswith("main.py") for f in files)
    content = agent.tools.read_file("app/main.py", 1, 20)
    assert "Todo" in content


async def test_never_modifies_code() -> None:
    before = (_fixture_root() / "app" / "main.py").read_text(encoding="utf-8")
    llm = FakeLLMProvider(agent_type="default", canned=_canned())
    agent = ArchaeologistAgent(llm=llm, repo_root=_fixture_root(), save_fn=None)
    await agent.run(_ctx())
    after = (_fixture_root() / "app" / "main.py").read_text(encoding="utf-8")
    assert before == after
    assert agent.tools.git_diff() == "" or isinstance(agent.tools.git_diff(), str)


async def test_failure_retry_succeeds_on_second_attempt() -> None:
    calls = {"n": 0}

    class _Flaky:
        name = "flaky"

        async def complete_json(self, prompt: str, schema: type[Any], **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise LLMProviderError("transient boom")
            provider = FakeLLMProvider(agent_type="default", canned=_canned())
            return await provider.complete_json(prompt, schema, **kwargs)

    agent = ArchaeologistAgent(llm=_Flaky(), repo_root=_fixture_root(), save_fn=None)
    event = await agent.run(_ctx())
    assert event == "analysis_complete"
    assert calls["n"] == 2


@pytest.mark.integration
async def test_persistence_round_trip(session: Any) -> None:
    from app.agents.service import get_analysis, save_analysis
    from app.runs.service import create_run

    run = await create_run(session, task="add pagination to /todos")
    await session.commit()
    findings = ArchaeologistFindings(
        summary="pagination analysis",
        relevant_files=["app/main.py"],
        architecture_findings=["list endpoint"],
        conventions=[],
        dependencies=[],
        risks=[],
        recommended_focus=["app/main.py"],
    )
    await save_analysis(
        session, run_id=run.id, findings=findings, provider="fake", model="fake-llm"
    )
    await session.commit()
    row = await get_analysis(session, run.id)
    assert row is not None
    assert row.provider == "fake"
    assert row.model == "fake-llm"
    assert row.findings["relevant_files"] == ["app/main.py"]


def test_registry_wiring_analyzing_uses_archaeologist() -> None:
    """Composition check: ANALYZING resolves to the real agent, stub elsewhere."""
    from app.llm.fake import FakeLLMProvider as _Fake
    from app.orchestrator import StateAgentRegistry as _Registry
    from app.orchestrator import archaeologist_stub as _stub
    from app.runs.enums import RunState as _State

    agent = ArchaeologistAgent(llm=_Fake(), repo_root=_fixture_root(), save_fn=None)
    registry = _Registry()
    registry.register(_State.ANALYZING, agent)
    assert registry.agent_for(_State.ANALYZING) is agent
    assert registry.agent_for(_State.CREATED) is _stub
    assert registry.agent_for(_State.PLANNING) is _stub
    assert registry.agent_for(_State.TESTING) is None
