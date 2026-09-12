"""Tester agent (Issue #009, AGENT_CONTRACTS §9).

On ``TESTING`` the Tester asks the LLM seam which validation commands
to run, executes them through the allowlisted pytest runner
(:mod:`app.agents.commands`), persists the parsed report with
provider/model (§12), and returns ``tests_passed`` or ``tests_failed``.

The Tester never edits code: it holds no workspace write handle and
the runner refuses anything but pytest (tested). Infrastructure
failures (bad exit codes, timeouts) raise instead of reporting —
a broken harness is not a test failure.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.commands import run_pytest
from app.agents.errors import AgentError
from app.agents.schemas import TestReport, TestSpec
from app.agents.workspace import WorkspaceManager
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

TESTS_PASSED_EVENT = "tests_passed"
TESTS_FAILED_EVENT = "tests_failed"
_MAX_RETRIES = 2


class TesterAgent:
    """Run the suite, parse it, report it. No edits, ever."""

    name: str = "tester"

    def __init__(
        self,
        *,
        llm: Any,
        workspaces: WorkspaceManager,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        model: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._llm = llm
        self._workspaces = workspaces
        self._save_fn = save_fn
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(1, max_retries)

    def _prompt(self, task: str, test_files: list[str]) -> str:
        return (
            "You are the Forge Tester. Decide which validation commands to run "
            "for the task. Return JSON matching the TestSpec schema: commands "
            "(pytest invocations only, e.g. 'pytest tests -q'), framework. "
            "Only the fixture test suite exists; do not invent other commands.\n"
            f"Task: {task}\nTest files: {test_files[:30]}"
        )

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        raw_run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        run_id = raw_run_id if isinstance(raw_run_id, uuid.UUID) else uuid.UUID(str(raw_run_id))

        workspace = self._workspaces.ensure(str(run_id))
        try:
            test_files = sorted(
                p.relative_to(workspace.path).as_posix()
                for p in workspace.path.rglob("test_*.py")
                if ".git" not in p.parts
            )
        except OSError:
            test_files = []
        prompt = self._prompt(task, test_files)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, TestSpec, model=self._model, timeout_s=30.0
                )
                spec = result.parsed
                if not isinstance(spec, TestSpec):
                    spec = TestSpec.model_validate(spec)
                if not spec.commands:
                    raise AgentError("tester received an empty command list")
                total_passed = total_failed = total_skipped = 0
                failures: list[str] = []
                ran: list[str] = []
                for command in spec.commands:
                    outcome = run_pytest(
                        workspace.path, command, timeout_seconds=self._timeout_seconds
                    )
                    ran.append(command)
                    total_passed += outcome.passed
                    total_failed += outcome.failed
                    total_skipped += outcome.skipped
                    failures.extend(failures_for(command, outcome.failures))
                status = "FAIL" if total_failed else "PASS"
                report = TestReport(
                    status=status,
                    commands=ran,
                    passed=total_passed,
                    failed=total_failed,
                    skipped=total_skipped,
                    failures=failures[:50],
                )
                if self._save_fn is not None:
                    await self._save_fn(
                        run_id=run_id,
                        result=report,
                        provider=getattr(self._llm, "name", "unknown"),
                        model=getattr(result, "model", self._model or "unknown"),
                    )
                log.info(
                    "tester_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    status=status,
                    passed=total_passed,
                    failed=total_failed,
                    request_id=request_id,
                )
                return TESTS_PASSED_EVENT if status == "PASS" else TESTS_FAILED_EVENT
            except (LLMProviderError, AgentError) as exc:
                last_error = exc
                log.warning(
                    "tester_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise AgentError(f"tester failed after {self._max_retries} attempts: {last_error}")


def failures_for(command: str, failures: list[str]) -> list[str]:
    """Prefix parsed failures with their command for multi-command reports."""
    return [f"{command} :: {failure}" for failure in failures]


__all__ = ["TESTS_FAILED_EVENT", "TESTS_PASSED_EVENT", "TesterAgent"]
