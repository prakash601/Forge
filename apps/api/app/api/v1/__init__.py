"""v1 API router.

Phase 1 issue #001 introduces the runs state machine endpoints
(``POST /runs``, ``POST /runs/{id}/events``, ``GET /runs/{id}``).
Additional v1 resources (projects, tasks, agents, memory) are added in
later issues and registered here.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.runs import router as runs_router

router = APIRouter()
router.include_router(runs_router)

__all__ = ["router"]
