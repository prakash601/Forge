"""HTTP endpoints for projects (v1, full CRUD per Issue #003).

Three endpoints:

  * ``POST /api/v1/projects``  — create a project (owner_id required).
  * ``GET  /api/v1/projects/{id}``  — read a project.
  * ``GET  /api/v1/projects``  — list projects for an owner (query string).

The list endpoint accepts ``?owner_id=...`` because projects are
always scoped to an owner; returning all projects across all owners
is not a use case in the MVP.

Error mapping follows the existing envelope contract: 404
``RESOURCE_NOT_FOUND`` (project or owner missing), 409 ``CONFLICT``
(rare; reserved for future per-owner name uniqueness).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session
from app.projects import service
from app.projects.errors import ProjectNotFoundError
from app.projects.schemas import ProjectCreate, ProjectRead
from app.users.errors import UserNotFoundError

router = APIRouter(prefix="/projects", tags=["projects"])
log = get_logger(__name__)


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project.",
    responses={404: {"description": "owner_id does not exist."}},
)
async def create_project_endpoint(
    request: Request,
    payload: ProjectCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProjectRead:
    try:
        project = await service.create_project(
            session,
            owner_id=payload.owner_id,
            name=payload.name,
            description=payload.description,
        )
    except UserNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
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
    summary="Read a project by id.",
    responses={404: {"description": "Project does not exist."}},
)
async def read_project_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> ProjectRead:
    try:
        project = await service.get_project(session, project_id)
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
    summary="List projects for an owner, newest first.",
    responses={404: {"description": "owner_id does not exist."}},
)
async def list_projects_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    owner_id: Annotated[uuid.UUID, Query(description="Owner user id.")],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProjectRead]:
    # Pre-check the owner exists for a clean 404. Without this,
    # an unknown owner_id would just return an empty list which is
    # confusing.
    from app.users import service as users_service

    try:
        await users_service.get_user(session, owner_id)
    except UserNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc

    projects = await service.list_projects_for_owner(session, owner_id, limit=limit, offset=offset)
    return [ProjectRead.model_validate(p) for p in projects]


__all__ = ["router"]
