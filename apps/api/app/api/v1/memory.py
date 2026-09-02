"""HTTP endpoints for project memory (v1, Issue #003).

Two endpoints:

  * ``POST /api/v1/projects/{project_id}/memory``  — create a memory item.
  * ``GET  /api/v1/projects/{project_id}/memory``  — list memory items.

The embedding is NOT exposed in the request or response. It is
populated asynchronously by a separate embedding-pipeline issue.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session
from app.memory import service
from app.memory.enums import MemoryStatus
from app.memory.schemas import MemoryItemCreate, MemoryItemList, MemoryItemRead
from app.projects.errors import ProjectNotFoundError

router = APIRouter(prefix="/projects/{project_id}/memory", tags=["memory"])
log = get_logger(__name__)


@router.post(
    "",
    response_model=MemoryItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new memory item for a project.",
    responses={404: {"description": "Project does not exist."}},
)
async def create_memory_item_endpoint(
    request: Request,
    payload: MemoryItemCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
) -> MemoryItemRead:
    try:
        item = await service.create_memory_item(
            session,
            project_id=project_id,
            memory_type=payload.memory_type,
            content=payload.content,
            title=payload.title,
            source_type=payload.source_type,
            source_id=payload.source_id,
            confidence=payload.confidence,
            repository_commit=payload.repository_commit,
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
    await session.commit()
    log.info(
        "memory_item_created",
        memory_item_id=str(item.id),
        project_id=str(project_id),
        memory_type=item.memory_type,
        request_id=request.state.request_id,
    )
    return MemoryItemRead.model_validate(item)


@router.get(
    "",
    response_model=MemoryItemList,
    status_code=status.HTTP_200_OK,
    summary="List memory items for a project, newest first.",
    responses={404: {"description": "Project does not exist."}},
)
async def list_memory_items_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: Annotated[uuid.UUID, Path(description="Project identifier (UUID).")],
    status_filter: Annotated[
        MemoryStatus | None,
        Query(alias="status", description="Filter by lifecycle status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MemoryItemList:
    try:
        items = await service.list_memory_items_for_project(
            session,
            project_id,
            status=status_filter,
            limit=limit,
            offset=offset,
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
    return MemoryItemList(
        items=[MemoryItemRead.model_validate(i) for i in items],
        count=len(items),
    )


__all__ = ["router"]
