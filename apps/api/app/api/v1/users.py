"""HTTP endpoints for users (v1, minimal).

``POST /api/v1/users`` is open (public signup). ``GET
/api/v1/users/{id}`` is self-only (Phase 4, Issue #016): any other id
is 404, indistinguishable from missing.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.logging import get_logger
from app.db.session import get_session
from app.users import service
from app.users.errors import DuplicateUserEmailError, UserNotFoundError
from app.users.models import User
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
    summary="Read the caller (self-only).",
    responses={404: {"description": "User does not exist or is not the caller."}},
)
async def read_user_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    user_id: Annotated[uuid.UUID, Path(description="User identifier (UUID).")],
) -> UserRead:
    if user_id != current_user.id:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": f"User {user_id!r} does not exist.",
                "request_id": request.state.request_id,
            },
        )
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
