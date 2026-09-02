"""v1 API router.

Phase 1 issue #001 introduced the runs state machine endpoints
(``POST /runs``, ``POST /runs/{id}/events``, ``GET /runs/{id}``).
Issue #002 added nothing HTTP-visible (orchestrator hooks existing
endpoints). Issue #003 adds:

  * ``POST /api/v1/users``, ``GET /api/v1/users/{id}``
  * ``POST /api/v1/projects``, ``GET /api/v1/projects``,
    ``GET /api/v1/projects/{id}``
  * ``POST /api/v1/projects/{id}/memory``,
    ``GET /api/v1/projects/{id}/memory``

Each new v1 resource is added as a sub-router and registered here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.memory import router as memory_router
from app.api.v1.projects import router as projects_router
from app.api.v1.runs import router as runs_router
from app.api.v1.users import router as users_router

router = APIRouter()
router.include_router(runs_router)
router.include_router(users_router)
router.include_router(projects_router)
router.include_router(memory_router)

__all__ = ["router"]
