"""Phase 2 real agents (Issues #007+).

``app.orchestrator.agents`` holds the Phase 1 stub. This package holds
real LLM-backed agents implementing the orchestrator ``Agent`` protocol.
"""

from __future__ import annotations

from app.agents.archaeologist import ArchaeologistAgent
from app.agents.commands import PytestOutcome, resolve_pytest_argv, run_pytest
from app.agents.debugger import DebuggerAgent
from app.agents.developer import DeveloperAgent
from app.agents.errors import AgentError, ArchaeologistError, ToolPermissionError, WorkspaceError
from app.agents.planner import PlannerAgent
from app.agents.policy import PolicyAutoApproveAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.schemas import (
    ArchaeologistFindings,
    DebuggerDiagnosis,
    DeveloperProposal,
    DeveloperResult,
    FileEdit,
    MemoryCandidate,
    Plan,
    PlanStep,
    ReviewDecision,
    TestReport,
    TestSpec,
)
from app.agents.tester import TesterAgent
from app.agents.workspace import Workspace, WorkspaceManager

__all__ = [
    "AgentError",
    "ArchaeologistAgent",
    "ArchaeologistError",
    "ArchaeologistFindings",
    "DebuggerAgent",
    "DebuggerDiagnosis",
    "DeveloperAgent",
    "DeveloperProposal",
    "DeveloperResult",
    "FileEdit",
    "MemoryCandidate",
    "Plan",
    "PlanStep",
    "PlannerAgent",
    "PolicyAutoApproveAgent",
    "PytestOutcome",
    "ReviewDecision",
    "ReviewerAgent",
    "TestReport",
    "TestSpec",
    "TesterAgent",
    "ToolPermissionError",
    "Workspace",
    "WorkspaceError",
    "WorkspaceManager",
    "resolve_pytest_argv",
    "run_pytest",
]
