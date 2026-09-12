"""Details + list endpoint tests (Issue #010)."""

from __future__ import annotations

from typing import Any

import pytest


async def test_details_fresh_run_has_null_sections(client: Any) -> None:
    created = await client.post("/api/v1/runs", json={"task": "fresh"})
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    response = await client.get(f"/api/v1/runs/{run_id}/details")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["steps"] == []
    for section in ("analysis", "plan", "implementation", "test_result", "diagnosis", "review"):
        assert body[section] is None, section
    assert body["memory_candidates"] == []
    assert body["approved_by"] is None


async def test_details_unknown_run_is_404(client: Any) -> None:
    import uuid

    response = await client.get(f"/api/v1/runs/{uuid.uuid4()}/details")
    assert response.status_code == 404


async def test_list_runs_newest_first(client: Any) -> None:
    first = await client.post("/api/v1/runs", json={"task": "first"})
    second = await client.post("/api/v1/runs", json={"task": "second"})
    assert first.status_code == 201 and second.status_code == 201

    response = await client.get("/api/v1/runs?limit=10")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert [r["id"] for r in body["runs"]] == [second.json()["id"], first.json()["id"]]


@pytest.mark.integration
async def test_details_populated(engine: Any, client: Any) -> None:
    """Phase 2 stores surface through the composite read."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.agents.schemas import (
        ArchaeologistFindings,
        DeveloperResult,
        MemoryCandidate,
        Plan,
        ReviewDecision,
        TestReport,
    )
    from app.agents.service import (
        save_analysis,
        save_implementation,
        save_memory,
        save_plan,
        save_review,
        save_test_result,
    )
    from app.runs import service as runs_service

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as db:
        run = await runs_service.create_run(db, task="populated")
        await db.commit()
        findings = ArchaeologistFindings(
            summary="s",
            relevant_files=["app/main.py"],
            architecture_findings=[],
            conventions=[],
            dependencies=[],
            risks=[],
            recommended_focus=[],
        )
        await save_analysis(db, run_id=run.id, findings=findings, provider="fake", model="f")
        plan = Plan(
            goal="g",
            approach="a",
            steps=[],
            files_to_change=["app/main.py"],
            files_to_add=[],
            tests=[],
            risks=[],
            rollback_strategy="r",
        )
        await save_plan(db, run_id=run.id, plan=plan, provider="fake", model="f")
        outcome = DeveloperResult(
            summary="d",
            files_changed=["app/main.py"],
            implementation_notes=[],
            validation=[],
            remaining_risks=[],
        )
        await save_implementation(
            db,
            run_id=run.id,
            result=outcome,
            provider="fake",
            model="f",
            workspace_path="ws",
        )
        report = TestReport(status="PASS", commands=["pytest"], passed=3, failed=0)
        await save_test_result(db, run_id=run.id, result=report, provider="fake", model="f")
        review = ReviewDecision(decision="APPROVE", summary="ok", findings=[])
        await save_review(db, run_id=run.id, review=review, provider="fake", model="f")
        await save_memory(
            db,
            run_id=run.id,
            candidates=[MemoryCandidate(memory_type="SUCCESSFUL_FIX", content="done")],
        )
        for event in ("repository_ready", "analysis_complete", "plan_ready"):
            await runs_service.transition(db, run.id, event)
        await runs_service.transition(db, run.id, "plan_approved", approved_by="human")
        await db.commit()
        run_id = str(run.id)

    response = await client.get(f"/api/v1/runs/{run_id}/details")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis"]["relevant_files"] == ["app/main.py"]
    assert body["plan"]["goal"] == "g"
    assert body["implementation"]["files_changed"] == ["app/main.py"]
    assert body["test_result"]["passed"] == 3
    assert body["diagnosis"] is None
    assert body["review"]["decision"] == "APPROVE"
    assert body["memory_candidates"][0]["memory_type"] == "SUCCESSFUL_FIX"
    assert body["approved_by"] == "human"
    assert len(body["run"]["steps"]) == 4
