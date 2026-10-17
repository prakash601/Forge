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

from app.auth.dependencies import cipher_or_503, get_current_user
from app.core.logging import get_logger
from app.db.session import get_session
from app.github.errors import InvalidRepoConfigError, InvalidRepoURLError
from app.github.service import connect_repo
from app.projects import service
from app.projects.errors import ProjectNotFoundError
from app.projects.schemas import (
    ProjectCreate,
    ProjectPatch,
    ProjectRead,
    RepoConnectRequest,
    RepoRead,
)
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
        auto_approve_policy=payload.auto_approve_policy,
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


@router.patch(
    "/{project_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_200_OK,
    summary="Update an owned project (owner only).",
    responses={404: {"description": "Project does not exist or is not yours."}},
)
async def update_project_endpoint(
    request: Request,
    payload: ProjectPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> ProjectRead:
    if payload.name is None and payload.description is None and payload.auto_approve_policy is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Nothing to update.",
                "request_id": request.state.request_id,
            },
        )
    try:
        project = await service.update_project(
            session,
            project_id=project_id,
            owner_id=current_user.id,
            name=payload.name,
            description=payload.description,
            auto_approve_policy=payload.auto_approve_policy,
        )
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
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    await session.commit()
    log.info(
        "project_updated",
        project_id=str(project.id),
        request_id=request.state.request_id,
    )
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


@router.post(
    "/{project_id}/repo",
    response_model=RepoRead,
    status_code=status.HTTP_200_OK,
    summary="Connect a GitHub repository (owner only).",
    responses={
        404: {"description": "Project does not exist or is not yours."},
        422: {"description": "Repo URL or branch invalid."},
    },
)
async def connect_repo_endpoint(
    request: Request,
    payload: RepoConnectRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> RepoRead:
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
    cipher = cipher_or_503(request)
    try:
        project = await connect_repo(
            session,
            project=project,
            repo_url=payload.repo_url,
            default_branch=payload.default_branch,
            credential=payload.credential,
            cipher=cipher,
        )
    except (InvalidRepoURLError, InvalidRepoConfigError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    await session.commit()
    log.info(
        "repo_connected",
        project_id=str(project.id),
        repo_url=project.repo_url,
        request_id=request.state.request_id,
    )
    assert project.repo_url is not None
    return RepoRead(
        repo_url=project.repo_url,
        default_branch=project.default_branch,
        credential_set=project.github_credential_ref is not None,
    )


@router.get(
    "/{project_id}/repo",
    response_model=RepoRead,
    status_code=status.HTTP_200_OK,
    summary="Read the connected repository (owner only).",
    responses={404: {"description": "Project missing, not yours, or no repo connected."}},
)
async def read_repo_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> RepoRead:
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
    if not project.repo_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": "No repository connected.",
                "request_id": request.state.request_id,
            },
        )
    return RepoRead(
        repo_url=project.repo_url,
        default_branch=project.default_branch,
        credential_set=project.github_credential_ref is not None,
    )


__all__ = ["router"]
