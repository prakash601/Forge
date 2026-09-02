"""HTTP endpoints for users (v1, minimal).

Issue #003 ships only the minimum surface needed to create a project
owner: ``POST /api/v1/users`` and ``GET /api/v1/users/{id}``. The
full user-management surface (sessions, OAuth, password reset)
belongs to a separate issue.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import get_session
from app.users import service
from app.users.errors import DuplicateUserEmailError, UserNotFoundError
from app.users.schemas import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])
log = get_logger(__name__)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user.",
)
async def create_user_endpoint(
    request: Request,
    payload: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserRead:
    try:
        user = await service.create_user(
            session,
            email=payload.email,
            display_name=payload.display_name,
        )
    except DuplicateUserEmailError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": str(exc),
                "request_id": request.state.request_id,
            },
        ) from exc
    await session.commit()
    log.info(
        "user_created",
        user_id=str(user.id),
        request_id=request.state.request_id,
    )
    return UserRead.model_validate(user)


@router.get(
    "/{user_id}",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Read a user by id.",
    responses={404: {"description": "User does not exist."}},
)
async def read_user_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[uuid.UUID, Path(description="User identifier (UUID).")],
) -> UserRead:
    try:
        user = await service.get_user(session, user_id)
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
    return UserRead.model_validate(user)


__all__ = ["router"]


# Suppress unused-import warning for symbols re-exported for tests.
_ = (ValidationError, IntegrityError)
