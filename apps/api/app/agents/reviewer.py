"""Reviewer agent (Issue #009, AGENT_CONTRACTS §11).

On ``REVIEWING`` the Reviewer reads the workspace diff, the test
report, and the plan, asks the LLM seam for a decision across the
seven review dimensions (correctness, scope, maintainability,
security, test coverage, regression risk, repository conventions),
persists the decision with provider/model (§12), records outcome
candidates for project memory, and returns ``review_passed``.

Anything but an explicit ``APPROVE`` returns ``escalate``: there is
no review-rejected event in the v0.1 state machine, so a rejection
parks the run with a human rather than looping silently.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.errors import AgentError
from app.agents.schemas import MemoryCandidate, Plan, ReviewDecision, TestReport
from app.agents.workspace import WorkspaceManager
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

REVIEW_PASSED_EVENT = "review_passed"
ESCALATE_EVENT = "escalate"
_MAX_RETRIES = 2

_DIMENSIONS = (
    "correctness",
    "scope",
    "maintainability",
    "security",
    "test coverage",
    "regression risk",
    "repository conventions",
)


async def _no_plan(**kwargs: object) -> Plan | None:
    return None


async def _no_test_result(**kwargs: object) -> TestReport | None:
    return None


def build_memory_candidates(
    task: str, review: ReviewDecision, report: TestReport | None, files_changed: list[str]
) -> list[MemoryCandidate]:
    """Deterministic outcome extracts for project memory.

    Candidates are derived from the persisted outcome — never hallucinated
    by the model — so a later Archaeologist can trust them.
    """
    tests = (
        f"{report.passed} passed, {report.failed} failed"
        if report is not None
        else "no test report"
    )
    candidates = [
        MemoryCandidate(
            memory_type="SUCCESSFUL_FIX" if review.decision == "APPROVE" else "FAILURE",
            content=f"{task} — {review.summary} (tests: {tests}).",
        )
    ]
    if files_changed:
        candidates.append(
            MemoryCandidate(
                memory_type="DISCOVERY",
                content=f"Change points for {task!r}: {', '.join(sorted(files_changed))}.",
            )
        )
    return candidates


class ReviewerAgent:
    """Diff + tests + plan → APPROVE or escalate. Never edits code."""

    name: str = "reviewer"

    def __init__(
        self,
        *,
        llm: Any,
        workspaces: WorkspaceManager,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        memory_fn: Callable[..., Awaitable[None]] | None = None,
        plan_provider: Callable[..., Awaitable[Any]] | None = None,
        test_result_provider: Callable[..., Awaitable[Any]] | None = None,
        model: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._llm = llm
        self._workspaces = workspaces
        self._save_fn = save_fn
        self._memory_fn = memory_fn
        self._plan_provider = plan_provider or _no_plan
        self._test_result_provider = test_result_provider or _no_test_result
        self._model = model
        self._max_retries = max(1, max_retries)

    def _prompt(self, task: str, plan: Plan | None, report: TestReport | None, diff: str) -> str:
        plan_text = (
            f"goal={plan.goal} files={plan.files_to_change + plan.files_to_add}"
            if plan is not None
            else "(no plan recorded)"
        )
        tests = (
            f"status={report.status} passed={report.passed} failed={report.failed}"
            if report is not None
            else "(no test report recorded)"
        )
        return (
            "You are the Forge Reviewer. Review the change across: "
            + ", ".join(_DIMENSIONS)
            + ". Return JSON matching the ReviewDecision schema: decision "
            "(APPROVE only if every dimension holds, else REJECT), summary, "
            "findings, blocking_findings.\n"
            f"Task: {task}\nPlan: {plan_text}\nTests: {tests}\nDiff:\n{diff[:6000]}"
        )

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        raw_run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        run_id = raw_run_id if isinstance(raw_run_id, uuid.UUID) else uuid.UUID(str(raw_run_id))

        workspace = self._workspaces.ensure(str(run_id))
        try:
            plan = await self._plan_provider(run_id=run_id)
        except Exception:
            plan = None
        try:
            report = await self._test_result_provider(run_id=run_id)
        except Exception:
            report = None
        if report is not None and not isinstance(report, TestReport):
            try:
                report = TestReport.model_validate(report)
            except Exception:
                report = None
        try:
            diff = workspace.diff()
        except Exception:
            diff = ""
        try:
            changed = [
                line.split()[-1] for line in diff.splitlines() if line.startswith("diff --git")
            ]
        except Exception:
            changed = []
        prompt = self._prompt(task, plan, report, diff)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, ReviewDecision, model=self._model, timeout_s=30.0
                )
                decision = result.parsed
                if not isinstance(decision, ReviewDecision):
                    decision = ReviewDecision.model_validate(decision)
                provider = getattr(self._llm, "name", "unknown")
                model = getattr(result, "model", self._model or "unknown")
                if self._save_fn is not None:
                    await self._save_fn(
                        run_id=run_id, review=decision, provider=provider, model=model
                    )
                if self._memory_fn is not None:
                    await self._memory_fn(
                        run_id=run_id,
                        candidates=build_memory_candidates(task, decision, report, changed),
                    )
                log.info(
                    "reviewer_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    decision=decision.decision,
                    request_id=request_id,
                )
                if decision.decision == "APPROVE":
                    return REVIEW_PASSED_EVENT
                return ESCALATE_EVENT
            except LLMProviderError as exc:
                last_error = exc
                log.warning(
                    "reviewer_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise AgentError(f"reviewer failed after {self._max_retries} attempts: {last_error}")


__all__ = ["ESCALATE_EVENT", "REVIEW_PASSED_EVENT", "ReviewerAgent", "build_memory_candidates"]
