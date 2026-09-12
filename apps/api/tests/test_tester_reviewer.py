"""Contract tests for Tester, Debugger, and Reviewer (Issue #009)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.commands import AgentError, resolve_pytest_argv, run_pytest
from app.agents.debugger import DebuggerAgent
from app.agents.reviewer import ReviewerAgent, build_memory_candidates
from app.agents.schemas import (
    DebuggerDiagnosis,
    MemoryCandidate,
    ReviewDecision,
    TestReport,
)
from app.agents.tester import TesterAgent
from app.agents.workspace import WorkspaceManager
from app.llm.fake import FakeLLMProvider
from app.orchestrator.context import AgentContext
from app.runs.enums import RunState

FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "todo-app"
PYTEST_CMD = "python -m pytest tests -q --tb=short -rf -p no:cacheprovider"


class _FakeRun:
    def __init__(self, task: str, state: RunState) -> None:
        self.id = uuid.uuid4()
        self.state = state
        self.task = task
        self.version = 0
        self.created_at = datetime.now(UTC)


def _ctx(task: str, state: RunState, steps: tuple[Any, ...] = ()) -> AgentContext:
    return AgentContext(run=_FakeRun(task, state), steps=steps, request_id="req_test")  # type: ignore[arg-type]


def _tester_canned() -> dict[str, dict[str, Any]]:
    return {"tester": {"commands": [PYTEST_CMD], "framework": "pytest"}}


def _manager(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(root=tmp_path / "ws", fixture_dir=FIXTURE_ROOT)


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


def test_resolve_pytest_argv_allowlists_pytest_only() -> None:
    assert resolve_pytest_argv("pytest tests -q")[1:] == ["-m", "pytest", "tests", "-q"]
    assert resolve_pytest_argv("python -m pytest tests")[1:] == ["-m", "pytest", "tests"]
    with pytest.raises(AgentError):
        resolve_pytest_argv("rm -rf /")
    with pytest.raises(AgentError):
        resolve_pytest_argv("npm test")
    with pytest.raises(AgentError):
        resolve_pytest_argv("")


def test_run_pytest_passes_on_fixture(tmp_path: Path) -> None:
    ws = _manager(tmp_path).ensure("run-cmd-ok")
    outcome = run_pytest(ws.path, PYTEST_CMD, timeout_seconds=120.0)
    assert outcome.exit_code == 0
    assert outcome.passed > 0
    assert outcome.failed == 0


def test_run_pytest_reports_failures(tmp_path: Path) -> None:
    ws = _manager(tmp_path).ensure("run-cmd-fail")
    ws.write_file("tests/test_broken.py", "def test_broken():\n    assert False\n")
    outcome = run_pytest(ws.path, PYTEST_CMD, timeout_seconds=120.0)
    assert outcome.exit_code == 1
    assert outcome.failed == 1
    assert any("test_broken" in failure for failure in outcome.failures)


def test_run_pytest_timeout_raises(tmp_path: Path) -> None:
    ws = _manager(tmp_path).ensure("run-cmd-timeout")
    with pytest.raises(AgentError, match="timed out"):
        run_pytest(ws.path, PYTEST_CMD, timeout_seconds=0.0001)


# ---------------------------------------------------------------------------
# Tester
# ---------------------------------------------------------------------------


async def test_tester_passes_and_persists(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, result: TestReport, **kwargs: Any) -> None:
        saved.update(result=result, provider=kwargs.get("provider"))

    agent = TesterAgent(
        llm=FakeLLMProvider(agent_type="tester", canned=_tester_canned()),
        workspaces=_manager(tmp_path),
        save_fn=_save,
    )
    event = await agent.run(_ctx("add pagination to /todos", RunState.TESTING))
    assert event == "tests_passed"
    report = saved["result"]
    assert isinstance(report, TestReport)
    assert report.status == "PASS"
    assert report.passed > 0 and report.failed == 0
    assert saved["provider"] == "fake"


async def test_tester_reports_failure(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, result: TestReport, **kwargs: Any) -> None:
        saved["result"] = result

    manager = _manager(tmp_path)
    run_id = uuid.uuid4()
    manager.ensure(str(run_id)).write_file(
        "tests/test_broken.py", "def test_broken():\n    assert False\n"
    )
    agent = TesterAgent(
        llm=FakeLLMProvider(agent_type="tester", canned=_tester_canned()),
        workspaces=manager,
        save_fn=_save,
    )
    ctx = AgentContext(
        run=_FakeRun("add pagination to /todos", RunState.TESTING), steps=(), request_id="r"
    )
    object.__setattr__(ctx.run, "id", run_id)
    assert await agent.run(ctx) == "tests_failed"
    assert saved["result"].status == "FAIL"
    assert saved["result"].failed == 1
    assert any("test_broken" in failure for failure in saved["result"].failures)


async def test_tester_denies_non_pytest_commands(tmp_path: Path) -> None:
    agent = TesterAgent(
        llm=FakeLLMProvider(
            agent_type="tester",
            canned={"tester": {"commands": ["rm -rf /"], "framework": "other"}},
        ),
        workspaces=_manager(tmp_path),
        save_fn=None,
    )
    with pytest.raises(AgentError):
        await agent.run(_ctx("add pagination to /todos", RunState.TESTING))


async def test_tester_malformed_output_raises(tmp_path: Path) -> None:
    agent = TesterAgent(
        llm=FakeLLMProvider(mode="malformed"),
        workspaces=_manager(tmp_path),
        save_fn=None,
    )
    with pytest.raises(AgentError):
        await agent.run(_ctx("add pagination to /todos", RunState.TESTING))


# ---------------------------------------------------------------------------
# Debugger
# ---------------------------------------------------------------------------


def _debugger_canned() -> dict[str, dict[str, Any]]:
    return {
        "debugger": {
            "root_cause": "Slice bounds are off by one.",
            "evidence": ["FAILED tests/test_todos.py::test_x"],
            "fix_strategy": "Adjust the slice and re-run pytest.",
            "confidence": 0.8,
        }
    }


def _failed_report() -> TestReport:
    return TestReport(
        status="FAIL",
        commands=[PYTEST_CMD],
        passed=10,
        failed=1,
        skipped=0,
        failures=["tests/test_todos.py::test_x"],
    )


async def test_debugger_returns_fix_ready(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, diagnosis: DebuggerDiagnosis, **kwargs: Any) -> None:
        saved["diagnosis"] = diagnosis

    async def _report(*, run_id: uuid.UUID, **kwargs: Any) -> TestReport:
        return _failed_report()

    agent = DebuggerAgent(
        llm=FakeLLMProvider(agent_type="debugger", canned=_debugger_canned()),
        workspaces=_manager(tmp_path),
        save_fn=_save,
        test_result_provider=_report,
    )
    steps = (SimpleNamespace(to_state="TESTING"), SimpleNamespace(to_state="DEBUGGING"))
    assert (
        await agent.run(_ctx("add pagination to /todos", RunState.DEBUGGING, steps)) == "fix_ready"
    )
    assert isinstance(saved["diagnosis"], DebuggerDiagnosis)
    assert saved["diagnosis"].confidence == 0.8


async def test_debugger_escalates_after_three_visits(tmp_path: Path) -> None:
    agent = DebuggerAgent(
        llm=FakeLLMProvider(agent_type="debugger", canned=_debugger_canned()),
        workspaces=_manager(tmp_path),
        save_fn=None,
    )
    steps = tuple(SimpleNamespace(to_state="DEBUGGING") for _ in range(3))
    assert (
        await agent.run(_ctx("add pagination to /todos", RunState.DEBUGGING, steps)) == "escalate"
    )


async def test_debugger_under_budget_returns_fix_ready(tmp_path: Path) -> None:
    agent = DebuggerAgent(
        llm=FakeLLMProvider(agent_type="debugger", canned=_debugger_canned()),
        workspaces=_manager(tmp_path),
        save_fn=None,
    )
    steps = tuple(SimpleNamespace(to_state="DEBUGGING") for _ in range(2))
    assert (
        await agent.run(_ctx("add pagination to /todos", RunState.DEBUGGING, steps)) == "fix_ready"
    )


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


def _reviewer_canned(decision: str = "APPROVE") -> dict[str, dict[str, Any]]:
    return {
        "reviewer": {
            "decision": decision,
            "summary": "Minimal pagination change with passing tests.",
            "findings": ["limit/offset slice in list_todos"],
            "blocking_findings": [],
        }
    }


async def test_reviewer_approves_and_records_memory(tmp_path: Path) -> None:
    saved: dict[str, Any] = {}

    async def _save(*, run_id: uuid.UUID, review: ReviewDecision, **kwargs: Any) -> None:
        saved["review"] = review

    async def _memory(*, run_id: uuid.UUID, candidates: list[MemoryCandidate]) -> None:
        saved["candidates"] = candidates

    async def _report(*, run_id: uuid.UUID, **kwargs: Any) -> TestReport:
        return TestReport(status="PASS", commands=[PYTEST_CMD], passed=12, failed=0)

    manager = _manager(tmp_path)
    agent = ReviewerAgent(
        llm=FakeLLMProvider(agent_type="reviewer", canned=_reviewer_canned()),
        workspaces=manager,
        save_fn=_save,
        memory_fn=_memory,
        test_result_provider=_report,
    )
    run_id = uuid.uuid4()
    ctx = AgentContext(
        run=_FakeRun("add pagination to /todos", RunState.REVIEWING), steps=(), request_id="r"
    )
    object.__setattr__(ctx.run, "id", run_id)
    manager.ensure(str(run_id))
    assert await agent.run(ctx) == "review_passed"
    assert saved["review"].decision == "APPROVE"
    assert len(saved["candidates"]) >= 1
    assert all(isinstance(c, MemoryCandidate) for c in saved["candidates"])


async def test_reviewer_reject_escalates(tmp_path: Path) -> None:
    async def _save(*, run_id: uuid.UUID, review: ReviewDecision, **kwargs: Any) -> None:
        pass

    manager = _manager(tmp_path)
    agent = ReviewerAgent(
        llm=FakeLLMProvider(agent_type="reviewer", canned=_reviewer_canned("REJECT")),
        workspaces=manager,
        save_fn=_save,
        memory_fn=None,
    )
    run_id = uuid.uuid4()
    ctx = AgentContext(
        run=_FakeRun("add pagination to /todos", RunState.REVIEWING), steps=(), request_id="r"
    )
    object.__setattr__(ctx.run, "id", run_id)
    manager.ensure(str(run_id))
    assert await agent.run(ctx) == "escalate"


def test_build_memory_candidates_is_deterministic() -> None:
    review = ReviewDecision(decision="APPROVE", summary="Looks good.", findings=[])
    report = TestReport(status="PASS", commands=[PYTEST_CMD], passed=5, failed=0)
    first = build_memory_candidates("task", review, report, ["app/main.py"])
    second = build_memory_candidates("task", review, report, ["app/main.py"])
    assert [c.model_dump() for c in first] == [c.model_dump() for c in second]
    assert first[0].memory_type == "SUCCESSFUL_FIX"


@pytest.mark.integration
async def test_verify_stores_round_trip(session: Any) -> None:
    from app.agents.service import (
        get_diagnosis,
        get_memory,
        get_review,
        get_test_result,
        save_diagnosis,
        save_memory,
        save_review,
        save_test_result,
    )
    from app.runs.service import create_run

    run = await create_run(session, task="add pagination to /todos")
    await session.commit()
    report = TestReport(status="PASS", commands=[PYTEST_CMD], passed=12, failed=0)
    await save_test_result(session, run_id=run.id, result=report, provider="fake", model="f")
    diagnosis = DebuggerDiagnosis(
        root_cause="rc", evidence=["e"], fix_strategy="fs", confidence=0.9
    )
    await save_diagnosis(session, run_id=run.id, diagnosis=diagnosis, provider="fake", model="f")
    review = ReviewDecision(decision="APPROVE", summary="ok", findings=[])
    await save_review(session, run_id=run.id, review=review, provider="fake", model="f")
    await save_memory(
        session,
        run_id=run.id,
        candidates=[MemoryCandidate(memory_type="SUCCESSFUL_FIX", content="done")],
    )
    await session.commit()

    assert (await get_test_result(session, run.id)).result["passed"] == 12  # type: ignore[union-attr]
    assert (await get_diagnosis(session, run.id)).diagnosis["confidence"] == 0.9  # type: ignore[union-attr]
    assert (await get_review(session, run.id)).review["decision"] == "APPROVE"  # type: ignore[union-attr]
    mem = await get_memory(session, run.id)
    assert mem is not None and mem.candidates[0]["memory_type"] == "SUCCESSFUL_FIX"
