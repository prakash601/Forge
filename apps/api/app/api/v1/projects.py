"""HTTP endpoints for projects (v1, Phase 4 Issue #016).

Three endpoints, all authenticated:

  * ``POST /api/v1/projects``  — create a project owned by the caller.
  * ``GET  /api/v1/projects/{id}``  — read a project (owner only, else 404).
  * ``GET  /api/v1/projects``  — list the caller's projects, newest first.

Tenancy (decided in #57): ownership is derived from the session, never
from client parameters. Missing and forbidden are indistinguishable
(404); unauthenticated callers get 401 from :func:`get_current_user`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
from app.db.session import get_session
from app.projects import service
from app.projects.errors import ProjectNotFoundError
from app.projects.schemas import ProjectCreate, ProjectRead
from app.users.models import User

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger(__name__)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project owned by the caller.",
)
async def create_project_endpoint(
    request: Request,
    payload: ProjectCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProjectRead:
    project = await service.create_project(
        session,
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
    )
    await session.commit()
    log.info(
        "project_created",
        project_id=str(project.id),
        owner_id=str(project.owner_id),
        request_id=request.state.request_id,
    )
    return ProjectRead.model_validate(project)


@router.get(
    "/{project_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_200_OK,
    summary="Read a project by id (owner only).",
    responses={404: {"description": "Project does not exist or is not yours."}},
)
async def read_project_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> ProjectRead:
    try:
        project = await service.get_owned_project(session, project_id, current_user.id)
    except ProjectNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    return ProjectRead.model_validate(project)


@router.get(
    "",
    response_model=list[ProjectRead],
    status_code=status.HTTP_200_OK,
    summary="List the caller's projects, newest first.",
)
async def list_projects_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProjectRead]:
    projects = await service.list_projects_for_owner(
        session, current_user.id, limit=limit, offset=offset
    )
    return [ProjectRead.model_validate(p) for p in projects]


__all__ = ["router"]
