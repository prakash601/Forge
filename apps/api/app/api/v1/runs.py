"""Run state machine HTTP endpoints (v1).

Three endpoints, exactly as specified in STATUS.md §4.2 for Issue #001:

  * ``POST /api/v1/runs`` — create a Run (state = CREATED).
  * ``POST /api/v1/runs/{run_id}/events`` — apply an event.
  * ``GET  /api/v1/runs/{run_id}`` — read a Run and its full step history.

Errors are translated into the envelope defined in
``app.core.errors.error_payload``:

  * 404 ``RESOURCE_NOT_FOUND``  — run does not exist.
  * 422 ``VALIDATION_ERROR``     — request body is invalid (empty task, etc.).
  * 409 ``CONFLICT``             — invalid transition or terminal state.

The module deliberately does NOT use ``from __future__ import
annotations`` because FastAPI evaluates the path-parameter annotation
``uuid.UUID`` at request time via :func:`typing.get_type_hints`, and
``uuid`` must be importable at that moment. Importing it locally and
referring to it as a string under ``from __future__ import annotations``
breaks dependency introspection in some FastAPI versions.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import error_payload
from app.core.logging import get_logger
from app.db.session import get_session
from app.runs import service
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.schemas import (
    RunCreateRequest,
    RunEventRequest,
    RunRead,
)

router = APIRouter(prefix="/runs", tags=["runs"])
log = get_logger(__name__)


@router.post(
    "",
    response_model=RunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Run in state CREATED.",
)
async def create_run_endpoint(
    request: Request,
    payload: RunCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunRead:
    run = await service.create_run(session, task=payload.task)
    await session.commit()
    log.info(
        "run_created",
        run_id=str(run.id),
        task_length=len(payload.task),
        request_id=request.state.request_id,
    )
    # Populate the ``steps`` relationship while the session is still
    # open; Pydantic will need it to build RunRead. A freshly created
    # Run has no steps yet, but the call is cheap and consistent with
    # the other endpoints.
    await session.refresh(run, attribute_names=["steps"])
    return RunRead.model_validate(run)


@router.post(
    "/{run_id}/events",
    response_model=RunRead,
    status_code=status.HTTP_200_OK,
    summary="Apply an event to a Run.",
    responses={
        404: {"description": "Run does not exist."},
        409: {"description": "Event is not allowed from the current state, or run is terminal."},
        422: {"description": "Event value is not a known event."},
    },
)
async def apply_event_endpoint(
    request: Request,
    payload: RunEventRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> RunRead:
    request_id: str = request.state.request_id
    try:
        run = await service.transition(session, run_id, payload.event)
    except RunNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    except (TerminalStateError, InvalidTransitionError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFLICT",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    except UnknownEventError as exc:
        await session.rollback()
        # 422 because the value is structurally valid but semantically
        # unknown — same shape as a request validation failure.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc

    await session.commit()
    log.info(
        "run_event_applied",
        run_id=str(run_id),
        run_event=payload.event,
        new_state=run.state.value,
        new_version=run.version,
        request_id=request_id,
    )
    # Populate ``steps`` while the session is still active so the
    # Pydantic response can be built without triggering lazy I/O.
    await session.refresh(run, attribute_names=["steps"])
    return RunRead.model_validate(run)


@router.get(
    "/{run_id}",
    response_model=RunRead,
    status_code=status.HTTP_200_OK,
    summary="Read a Run and its full step history.",
    responses={404: {"description": "Run does not exist."}},
)
async def read_run_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> RunRead:
    request_id: str = request.state.request_id
    try:
        run = await service.get_run(session, run_id)
    except RunNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc

    # Eagerly load steps for the response. ``Run.steps`` uses
    # ``lazy="selectin"`` already, but we refresh the read so the payload
    # is fully populated before we return.
    await session.refresh(run, attribute_names=["steps"])
    return RunRead.model_validate(run)


# Re-exported so other modules (and tests) can import without reaching
# into a private name.
__all__ = ["error_payload", "router"]
