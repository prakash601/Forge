"""Planner capability (Issue #008, PRD §12).

An orchestrator capability rather than a full agent: on ``PLANNING`` it
combines the task with the Archaeologist findings, asks the LLM seam
for a validated plan (AGENT_CONTRACTS §7), persists it with
provider/model (§12), and returns ``plan_ready``.

The planner holds read-only repo tools only. It never edits code:
it receives no workspace handle, and the permission table denies
writes (tested).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agents.errors import ArchaeologistError
from app.agents.schemas import ArchaeologistFindings, Plan
from app.agents.tools import ReadOnlyRepoTools
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

PLAN_READY_EVENT = "plan_ready"
_MAX_RETRIES = 2


async def _no_findings(**kwargs: Any) -> ArchaeologistFindings | None:
    return None


class PlannerAgent:
    """Findings + task → validated plan. No writes, ever."""

    name: str = "planner"

    def __init__(
        self,
        *,
        llm: Any,
        repo_root: Path,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        findings_provider: Callable[..., Awaitable[Any]] | None = None,
        model: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._llm = llm
        self._tools = ReadOnlyRepoTools(root=repo_root)
        self._save_fn = save_fn
        self._findings_provider = findings_provider or _no_findings
        self._model = model
        self._max_retries = max(1, max_retries)

    @property
    def tools(self) -> ReadOnlyRepoTools:
        return self._tools

    def _prompt(self, task: str, findings: ArchaeologistFindings | None) -> str:
        if findings is None:
            evidence = "(no archaeologist findings recorded for this run)"
        else:
            evidence = (
                f"Archaeologist summary: {findings.summary}\n"
                f"Relevant files: {findings.relevant_files}\n"
                f"Findings: {findings.findings_list()}\n"
                f"Conventions: {findings.conventions}\n"
                f"Dependencies: {findings.dependencies}\n"
                f"Risks: {findings.risks}\n"
                f"Recommended focus: {findings.recommended_focus}"
            )
        return (
            "You are the Forge Planner. Draft the implementation plan for the task. "
            "Return JSON matching the Plan schema: goal, approach, steps, "
            "files_to_change, files_to_add, tests, risks, rollback_strategy. "
            "Scope the plan to the fixture repo; do not invent files outside it.\n"
            f"Task: {task}\n{evidence}"
        )

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        try:
            findings = await self._findings_provider(
                run_id=run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id))
            )
        except Exception:
            findings = None
        prompt = self._prompt(task, findings)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, Plan, model=self._model, timeout_s=30.0
                )
                plan = result.parsed
                if not isinstance(plan, Plan):
                    plan = Plan.model_validate(plan)
                if self._save_fn is not None and run_id is not None:
                    await self._save_fn(
                        run_id=run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id)),
                        plan=plan,
                        provider=getattr(self._llm, "name", "unknown"),
                        model=getattr(result, "model", self._model or "unknown"),
                    )
                log.info(
                    "planner_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    provider=getattr(self._llm, "name", "unknown"),
                    request_id=request_id,
                )
                return PLAN_READY_EVENT
            except LLMProviderError as exc:
                last_error = exc
                log.warning(
                    "planner_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise ArchaeologistError(f"planner failed after {self._max_retries} attempts: {last_error}")


__all__ = ["PLAN_READY_EVENT", "PlannerAgent"]
