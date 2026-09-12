"""Phase 2 real agents (Issues #007+).

``app.orchestrator.agents`` holds the Phase 1 stub. This package holds
real LLM-backed agents implementing the orchestrator ``Agent`` protocol.
"""

from __future__ import annotations

from app.agents.archaeologist import ArchaeologistAgent
from app.agents.developer import DeveloperAgent
from app.agents.errors import ArchaeologistError, ToolPermissionError, WorkspaceError
from app.agents.planner import PlannerAgent
from app.agents.policy import PolicyAutoApproveAgent
from app.agents.schemas import (
    ArchaeologistFindings,
    DeveloperProposal,
    DeveloperResult,
    FileEdit,
    Plan,
    PlanStep,
)
from app.agents.workspace import Workspace, WorkspaceManager

__all__ = [
    "ArchaeologistAgent",
    "ArchaeologistError",
    "ArchaeologistFindings",
    "DeveloperAgent",
    "DeveloperProposal",
    "DeveloperResult",
    "FileEdit",
    "Plan",
    "PlanStep",
    "PlannerAgent",
    "PolicyAutoApproveAgent",
    "ToolPermissionError",
    "Workspace",
    "WorkspaceError",
    "WorkspaceManager",
]
