"""Developer agent (Issue #008, AGENT_CONTRACTS §8).

On ``IMPLEMENTING`` the Developer loads the approved plan, asks the
LLM seam for a :class:`DeveloperProposal` (edits plus §8 result
fields), applies the edits to the per-run workspace, persists the
:class:`DeveloperResult` with provider/model (§12), and returns
``implementation_complete``.

Blast-radius guard: only edits whose path appears in the plan's
``files_to_change``/``files_to_add`` are applied; anything else is
skipped and noted, so unrelated changes stay minimal by construction.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.agents.errors import ArchaeologistError, WorkspaceError
from app.agents.schemas import DebuggerDiagnosis, DeveloperProposal, DeveloperResult, Plan
from app.agents.workspace import WorkspaceManager
from app.core.logging import get_logger
from app.llm.errors import LLMProviderError

log = get_logger(__name__)

IMPLEMENTATION_COMPLETE_EVENT = "implementation_complete"
_MAX_RETRIES = 2


async def _no_plan(**kwargs: Any) -> Plan | None:
    return None


class DeveloperAgent:
    """Approved plan → workspace-local edits. No unrelated changes."""

    name: str = "developer"

    def __init__(
        self,
        *,
        llm: Any,
        workspaces: WorkspaceManager,
        save_fn: Callable[..., Awaitable[None]] | None = None,
        plan_provider: Callable[..., Awaitable[Any]] | None = None,
        diagnosis_provider: Callable[..., Awaitable[Any]] | None = None,
        model: str | None = None,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._llm = llm
        self._workspaces = workspaces
        self._save_fn = save_fn
        self._plan_provider = plan_provider or _no_plan
        self._diagnosis_provider = diagnosis_provider
        self._model = model
        self._max_retries = max(1, max_retries)

    def _prompt(
        self, task: str, plan: Plan, repo_hint: str, diagnosis: DebuggerDiagnosis | None
    ) -> str:
        prompt = (
            "You are the Forge Developer. Implement the approved plan with "
            "minimal workspace-local edits. Return JSON matching the "
            "DeveloperProposal schema: edits (path, mode write|edit, "
            "content/old_text/new_text), summary, implementation_notes, "
            "validation, remaining_risks. Only touch files listed in the "
            "plan; never invent unrelated changes.\n"
            f"Task: {task}\n"
            f"Goal: {plan.goal}\nApproach: {plan.approach}\n"
            f"Steps: {[s.title for s in plan.steps]}\n"
            f"Files to change: {plan.files_to_change}\n"
            f"Files to add: {plan.files_to_add}\n"
            f"Tests: {plan.tests}\nRisks: {plan.risks}\n"
            f"Workspace hint:\n{repo_hint[:2000]}"
        )
        if diagnosis is not None:
            prompt += (
                "\nDebugger diagnosis to apply: "
                f"root cause: {diagnosis.root_cause}; "
                f"fix strategy: {diagnosis.fix_strategy}; "
                f"evidence: {diagnosis.evidence[:5]}"
            )
        return prompt

    async def run(self, context: Any) -> str | None:
        task = str(getattr(context, "task", "") or "")
        raw_run_id = getattr(context, "run_id", None)
        request_id = str(getattr(context, "request_id", ""))
        run_id = raw_run_id if isinstance(raw_run_id, uuid.UUID) else uuid.UUID(str(raw_run_id))
        try:
            plan = await self._plan_provider(run_id=run_id)
        except Exception:
            plan = None
        if plan is None:
            raise ArchaeologistError(f"developer has no approved plan for run {run_id}")
        diagnosis: DebuggerDiagnosis | None = None
        if self._diagnosis_provider is not None:
            try:
                candidate = await self._diagnosis_provider(run_id=run_id)
                diagnosis = (
                    candidate
                    if isinstance(candidate, DebuggerDiagnosis)
                    else DebuggerDiagnosis.model_validate(candidate)
                    if candidate is not None
                    else None
                )
            except Exception:
                diagnosis = None

        workspace = self._workspaces.ensure(str(run_id))
        try:
            repo_hint = workspace.read_file("app/main.py", 3000)
        except WorkspaceError:
            repo_hint = ""
        prompt = self._prompt(task, plan, repo_hint, diagnosis)
        allowed = set(plan.files_to_change) | set(plan.files_to_add)

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._llm.complete_json(
                    prompt, DeveloperProposal, model=self._model, timeout_s=60.0
                )
                proposal = result.parsed
                if not isinstance(proposal, DeveloperProposal):
                    proposal = DeveloperProposal.model_validate(proposal)
                changed: list[str] = []
                skipped: list[str] = []
                for edit in proposal.edits:
                    if edit.path not in allowed:
                        skipped.append(edit.path)
                        continue
                    if edit.mode == "write":
                        workspace.write_file(edit.path, edit.content or "")
                    else:
                        workspace.edit_file(edit.path, edit.old_text or "", edit.new_text or "")
                    if edit.path not in changed:
                        changed.append(edit.path)
                notes = list(proposal.implementation_notes)
                if skipped:
                    notes.append(f"skipped out-of-plan edits: {sorted(set(skipped))}")
                outcome = DeveloperResult(
                    summary=proposal.summary,
                    files_changed=sorted(changed),
                    implementation_notes=notes,
                    validation=proposal.validation,
                    remaining_risks=proposal.remaining_risks,
                )
                if self._save_fn is not None:
                    await self._save_fn(
                        run_id=run_id,
                        result=outcome,
                        provider=getattr(self._llm, "name", "unknown"),
                        model=getattr(result, "model", self._model or "unknown"),
                        workspace_path=str(workspace.path),
                    )
                log.info(
                    "developer_completed",
                    run_id=str(run_id),
                    attempt=attempt,
                    files_changed=sorted(changed),
                    request_id=request_id,
                )
                return IMPLEMENTATION_COMPLETE_EVENT
            except (LLMProviderError, WorkspaceError) as exc:
                last_error = exc
                log.warning(
                    "developer_attempt_failed",
                    run_id=str(run_id),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    request_id=request_id,
                )
                continue
        raise ArchaeologistError(
            f"developer failed after {self._max_retries} attempts: {last_error}"
        )


__all__ = ["IMPLEMENTATION_COMPLETE_EVENT", "DeveloperAgent"]
