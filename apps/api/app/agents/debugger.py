"""Debugger capability (Issue #009, PRD §12).

An orchestrator capability rather than a full agent: on ``DEBUGGING``
it combines the failed test report, the workspace diff, and the task,
asks the LLM seam for a diagnosis (AGENT_CONTRACTS §10), persists it
with provider/model (§12), and returns ``fix_ready`` so the Developer
gets another iteration.

Bounded retries (STATE_MACHINE §7): the debugger counts prior
``DEBUGGING`` visits in the run history. Past ``max_debug_attempts``
it returns ``escalate`` (→ NEEDS_HUMAN) instead of looping forever.
The debugger diagnoses; it never edits code itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.errors import AgentError
from app.agents.schemas import DebuggerDiagnosis, TestReport
from app.agents.workspace import WorkspaceManager
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

FIX_READY_EVENT = "fix_ready"
ESCALATE_EVENT = "escalate"
MAX_DEBUG_ATTEMPTS = 3
_MAX_LLM_RETRIES = 2


async def _no_test_result(**kwargs: object) -> TestReport | None:
    return None


class DebuggerAgent:
    """Failed tests + logs + diff → root cause + fix strategy."""

    name: str = "debugger"

    def __init__(
        self,
        *,
        llm: Any,
        workspaces: WorkspaceManager,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        test_result_provider: Callable[..., Awaitable[Any]] | None = None,
        model: str | None = None,
        max_debug_attempts: int = MAX_DEBUG_ATTEMPTS,
        max_retries: int = _MAX_LLM_RETRIES,
    ) -> None:
        self._llm = llm
        self._workspaces = workspaces
        self._save_fn = save_fn
        self._test_result_provider = test_result_provider or _no_test_result
        self._model = model
        self._max_debug_attempts = max(1, max_debug_attempts)
        self._max_retries = max(1, max_retries)

    @staticmethod
    def debug_visits(steps: tuple[Any, ...]) -> int:
        """Count prior DEBUGGING visits in the run history."""
        return sum(1 for step in steps if getattr(step, "to_state", None) == "DEBUGGING")

    def _prompt(self, task: str, report: TestReport | None, diff: str) -> str:
        if report is None:
            tests = "(no test report recorded for this run)"
        else:
            tests = (
                f"status={report.status} passed={report.passed} "
                f"failed={report.failed} skipped={report.skipped}\n"
                f"failures:\n" + "\n".join(report.failures[:20])
            )
        return (
            "You are the Forge Debugger. Diagnose the failing run and propose "
            "a fix strategy. Return JSON matching the DebuggerDiagnosis schema: "
            "root_cause, evidence, fix_strategy, confidence (0-1). "
            "Diagnose only; do not propose unrelated changes.\n"
            f"Task: {task}\nTest results:\n{tests}\nDiff:\n{diff[:4000]}"
        )

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        raw_run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        run_id = raw_run_id if isinstance(raw_run_id, uuid.UUID) else uuid.UUID(str(raw_run_id))
        steps = tuple(getattr(context, "steps", ()) or ())

        visits = self.debug_visits(steps)
        if visits >= self._max_debug_attempts:
            log.warning(
                "debugger_budget_exhausted",
                run_id=str(run_id),
                visits=visits,
                request_id=request_id,
            )
            return ESCALATE_EVENT

        workspace = self._workspaces.ensure(str(run_id))
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
        prompt = self._prompt(task, report, diff)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, DebuggerDiagnosis, model=self._model, timeout_s=30.0
                )
                diagnosis = result.parsed
                if not isinstance(diagnosis, DebuggerDiagnosis):
                    diagnosis = DebuggerDiagnosis.model_validate(diagnosis)
                if self._save_fn is not None:
                    await self._save_fn(
                        run_id=run_id,
                        diagnosis=diagnosis,
                        provider=getattr(self._llm, "name", "unknown"),
                        model=getattr(result, "model", self._model or "unknown"),
                    )
                log.info(
                    "debugger_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    visits=visits,
                    request_id=request_id,
                )
                return FIX_READY_EVENT
            except LLMProviderError as exc:
                last_error = exc
                log.warning(
                    "debugger_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise AgentError(f"debugger failed after {self._max_retries} attempts: {last_error}")


__all__ = ["ESCALATE_EVENT", "FIX_READY_EVENT", "MAX_DEBUG_ATTEMPTS", "DebuggerAgent"]
