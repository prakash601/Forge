"""LLM-backed Archaeologist agent (Issue #007).

Implements the orchestrator ``Agent`` protocol: on ``ANALYZING`` it
gathers read-only evidence from the fixture repo, optionally prepends
retrieved memory, calls the LLM seam for schema-valid findings
(AGENT_CONTRACTS §6), persists them with provider/model (§12), and
returns ``analysis_complete``. Never modifies code.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agents.errors import ArchaeologistError
from app.agents.schemas import ArchaeologistFindings
from app.agents.tools import ReadOnlyRepoTools
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

ANALYSIS_COMPLETE_EVENT = "analysis_complete"
_MAX_RETRIES = 2

_FOCUS_FILES = ("app/main.py", "tests/test_todos.py", "requirements.txt", "README.md")


async def _default_memory() -> list[str]:
    return []


class ArchaeologistAgent:
    """First real agent in the Phase 2 loop."""

    name: str = "archaeologist"

    def __init__(
        self,
        *,
        llm: Any,
        repo_root: Path,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        memory_reader: Callable[[], Awaitable[list[str]]] | None = None,
        model: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._llm = llm
        self._tools = ReadOnlyRepoTools(root=repo_root)
        self._save_fn = save_fn
        self._memory_reader = memory_reader or _default_memory
        self._model = model
        self._max_retries = max(1, max_retries)

    @property
    def tools(self) -> ReadOnlyRepoTools:
        return self._tools

    def _evidence(self, task: str) -> str:
        parts: list[str] = [f"Task: {task}"]
        try:
            files = self._tools.list_files(".", "*.py")
        except Exception:
            files = []
        parts.append(f"Python files: {files[:40]}")
        for rel in _FOCUS_FILES:
            try:
                content = self._tools.read_file(rel, 1, 120)
                parts.append(f"--- {rel} ---\n{content[:3000]}")
            except FileNotFoundError:
                continue
            except Exception as exc:
                parts.append(f"--- {rel} unreadable: {exc} ---")
        try:
            hits = self._tools.search_code("/todos", ".", 20)
            parts.append(f"search('/todos'): {hits[:20]}")
        except Exception as exc:
            parts.append(f"search unavailable: {exc}")
        diff = self._tools.git_diff()
        if diff:
            parts.append(f"git diff --stat:\n{diff[:1000]}")
        return "\n".join(parts)[:9000]

    def _prompt(self, task: str, evidence: str, memory: list[str]) -> str:
        mem = "\n".join(memory[:10]) if memory else "(no retrieved memory)"
        return (
            "You are the Forge Archaeologist. Analyze the fixture repo. "
            "Return JSON for ArchaeologistFindings: summary, relevant_files, "
            "architecture_findings, conventions, dependencies, risks, focus. "
            "Be specific to the Todo fixture (routes, store, tests/).\n"
            f"Retrieved memory:\n{mem}\nEvidence:\n{evidence}"
        )

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        try:
            memory = await self._memory_reader()
        except Exception:
            memory = []
        evidence = self._evidence(task)
        prompt = self._prompt(task, evidence, memory)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, ArchaeologistFindings, model=self._model, timeout_s=30.0
                )
                findings = result.parsed
                if not isinstance(findings, ArchaeologistFindings):
                    findings = ArchaeologistFindings.model_validate(findings)
                if self._save_fn is not None and run_id is not None:
                    await self._save_fn(
                        run_id=run_id if isinstance(run_id, uuid.UUID) else uuid.UUID(str(run_id)),
                        findings=findings,
                        provider=getattr(self._llm, "name", "unknown"),
                        model=getattr(result, "model", self._model or "unknown"),
                    )
                log.info(
                    "archaeologist_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    provider=getattr(self._llm, "name", "unknown"),
                    model=getattr(result, "model", self._model or "unknown"),
                    request_id=request_id,
                )
                return ANALYSIS_COMPLETE_EVENT
            except LLMProviderError as exc:
                last_error = exc
                log.warning(
                    "archaeologist_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise ArchaeologistError(
            f"archaeologist failed after {self._max_retries} attempts: {last_error}"
        )


__all__ = ["ANALYSIS_COMPLETE_EVENT", "ArchaeologistAgent"]
