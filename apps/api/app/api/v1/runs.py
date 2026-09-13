"""Run state machine HTTP endpoints (v1).

  * ``POST /api/v1/runs`` — create a Run in a caller-owned project.
  * ``POST /api/v1/runs/{run_id}/events`` — apply an event.
  * ``GET  /api/v1/runs/{run_id}`` — read a Run and its full step history.
  * ``GET  /api/v1/runs`` — list the caller's runs (auto-scoped).
  * ``GET  /api/v1/runs/{run_id}/details`` — composite dashboard read.
  * ``GET  /api/v1/runs/{run_id}/stream`` — SSE timeline.

Tenancy (Phase 4, Issue #016): every endpoint requires the session
(:func:`get_current_user`) and every run access is ownership-checked
(:func:`get_owned_run`). Missing and forbidden are 404
``RESOURCE_NOT_FOUND``; unauthenticated callers get 401.

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

import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path as FsPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.errors import NoGitHubCredentialError
from app.auth.tokens import TokenCipher
from app.core.errors import error_payload
from app.core.logging import get_logger
from app.db.session import get_session, get_session_factory
from app.github.credentials import resolve_credential
from app.github.errors import GitOperationError
from app.github.repos import clone_repo, is_auth_failure, task_branch_name
from app.orchestrator.orchestrator import Orchestrator
from app.projects.errors import ProjectNotFoundError
from app.projects.models import Project
from app.projects.service import get_owned_project, list_owned_project_ids
from app.runs import service
from app.runs.details import RunDetails, get_run_details
from app.runs.enums import RunState, is_terminal_state
from app.runs.errors import (
    InvalidTransitionError,
    RunNotFoundError,
    TerminalStateError,
    UnknownEventError,
)
from app.runs.schemas import (
    RunCreateRequest,
    RunEventRequest,
    RunList,
    RunRead,
    RunStepRead,
)
from app.users.models import User

router = APIRouter(prefix="/runs", tags=["runs"])
log = get_logger(__name__)


async def _clone_for_run(
    request: Request,
    session: AsyncSession,
    *,
    project: Project,
    run_id: uuid.UUID,
    task: str,
) -> None:
    """Clone the connected repo into the run workspace (repo-backed runs).

    Sets ``run.branch``/``run.base_commit``. On any failure the run is
    rolled back and the request fails: rejected credentials are 400
    (user-fixable: reconnect), anything else 502. Messages are
    redacted (URLs carry no credentials by construction).
    """
    request_id: str = request.state.request_id
    settings = request.app.state.settings
    assert project.repo_url is not None and project.github_credential_ref is not None
    if not settings.credentials_key:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AUTH_NOT_CONFIGURED",
                "message": "Auth is not configured (missing credentials_key).",
                "request_id": request_id,
            },
        )
    try:
        credential = await resolve_credential(
            session,
            ref=project.github_credential_ref,
            cipher=TokenCipher(settings.credentials_key),
        )
    except (NoGitHubCredentialError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "GITHUB_AUTH_ERROR",
                "message": "No usable GitHub credential; reconnect the repository.",
                "request_id": request_id,
            },
        ) from exc
    branch = task_branch_name(task, run_id)
    dest = FsPath(settings.workspace_root) / str(run_id)
    try:
        base_commit = await clone_repo(
            repo_url=project.repo_url,
            dest=dest,
            branch=branch,
            default_branch=project.default_branch,
            credential=credential,
        )
    except GitOperationError as exc:
        await session.rollback()
        if is_auth_failure(exc):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "GITHUB_AUTH_ERROR",
                    "message": "GitHub rejected the credential; reconnect the repository.",
                    "request_id": request_id,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "GITHUB_UPSTREAM_ERROR",
                "message": f"Could not clone the repository: {exc}",
                "request_id": request_id,
            },
        ) from exc
    run = await service.get_run(session, run_id)
    run.branch = branch
    run.base_commit = base_commit
    await session.flush()
    log.info(
        "repo_cloned",
        run_id=str(run_id),
        branch=branch,
        base_commit=base_commit[:12] if base_commit else None,
        request_id=request_id,
    )


def _orchestrator(request: Request) -> Orchestrator | None:
    """Return the app-scoped orchestrator, or None if not installed.

    The orchestrator is installed by the FastAPI lifespan handler. In
    unit tests that build the app without lifespan, ``app.state`` may
    not have it; we return ``None`` and the caller skips the hook so
    the existing tests (Issue #001) keep passing.
    """
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is None:
        log.debug("orchestrator_not_installed_skipping_hook")
    return orchestrator


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
    current_user: Annotated[User, Depends(get_current_user)],
) -> RunRead:
    request_id: str = request.state.request_id
    try:
        project = await get_owned_project(session, payload.project_id, current_user.id)
    except ProjectNotFoundError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RESOURCE_NOT_FOUND",
                "message": str(exc),
                "request_id": request_id,
            },
        ) from exc
    run = await service.create_run(session, task=payload.task, project_id=project.id)
    await session.flush()  # populate run.id for the branch name
    if project.repo_url:
        await _clone_for_run(request, session, project=project, run_id=run.id, task=payload.task)
        await session.refresh(run)
    await session.commit()
    log.info(
        "run_created",
        run_id=str(run.id),
        project_id=str(project.id),
        task_length=len(payload.task),
        request_id=request.state.request_id,
    )
    # Populate the ``steps`` relationship while the session is still
    # open; Pydantic will need it to build RunRead. A freshly created
    # Run has no steps yet, but the call is cheap and consistent with
    # the other endpoints.
    await session.refresh(run, attribute_names=["steps"])
    response = RunRead.model_validate(run)

    # Hook: notify the orchestrator that a new Run exists in CREATED.
    # The driver will schedule the next agent task if one is registered.
    orchestrator = _orchestrator(request)
    if orchestrator is not None:
        orchestrator.handle_transition(
            run_id=run.id,
            from_state=RunState.CREATED,  # pre-state (no transition yet)
            to_state=RunState.CREATED,
            event="<create>",
            request_id=request.state.request_id,
        )
    return response


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
    current_user: Annotated[User, Depends(get_current_user)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> RunRead:
    request_id: str = request.state.request_id
    # An explicit approval over HTTP is a person driving the run, so it
    # records approved_by=human. Machine approvals arrive via the
    # orchestrator (approved_by=policy); see CONTEXT.md.
    approved_by = "human" if payload.event == "plan_approved" else None
    try:
        await service.get_owned_run(session, run_id, current_user.id)
        run = await service.transition(session, run_id, payload.event, approved_by=approved_by)
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
        user_id=str(current_user.id),
        request_id=request_id,
    )
    # Populate ``steps`` while the session is still active so the
    # Pydantic response can be built without triggering lazy I/O.
    await session.refresh(run, attribute_names=["steps"])
    response = RunRead.model_validate(run)

    # Hook: notify the orchestrator. We captured the from_state on the
    # Run instance inside ``service.transition()`` as a transient
    # attribute; default to the new state if missing (defensive).
    orchestrator = _orchestrator(request)
    if orchestrator is not None:
        from_state: RunState = getattr(run, "_from_state", run.state)
        orchestrator.handle_transition(
            run_id=run.id,
            from_state=from_state,
            to_state=run.state,
            event=payload.event,
            request_id=request_id,
        )
    return response


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
    current_user: Annotated[User, Depends(get_current_user)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> RunRead:
    request_id: str = request.state.request_id
    try:
        run = await service.get_owned_run(session, run_id, current_user.id)
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


@router.get(
    "",
    response_model=RunList,
    status_code=status.HTTP_200_OK,
    summary="List runs newest-first (dashboard foundation).",
)
async def list_runs_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    project_ids = await list_owned_project_ids(session, current_user.id)
    runs, total = await service.list_runs(
        session, limit=limit, offset=offset, project_ids=project_ids
    )
    return RunList(runs=[RunRead.model_validate(run) for run in runs], total=total)


@router.get(
    "/{run_id}/details",
    response_model=RunDetails,
    status_code=status.HTTP_200_OK,
    summary="Composite dashboard read for one run.",
    responses={404: {"description": "Run does not exist."}},
)
async def read_run_details_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> RunDetails:
    request_id: str = request.state.request_id
    try:
        await service.get_owned_run(session, run_id, current_user.id)
        return await get_run_details(session, run_id)
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


@router.get(
    "/{run_id}/stream",
    status_code=status.HTTP_200_OK,
    summary="Server-sent-events timeline for one run (closes on terminal state).",
    responses={404: {"description": "Run does not exist."}},
)
async def stream_run_endpoint(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
    run_id: Annotated[uuid.UUID, Path(description="Run identifier (UUID).")],
) -> StreamingResponse:
    request_id: str = request.state.request_id
    try:
        await service.get_owned_run(session, run_id, current_user.id)
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
    return StreamingResponse(
        _run_events(run_id=run_id, owner_id=current_user.id, request_id=request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: object) -> str:
    import json as _json

    return f"event: {event}\ndata: {_json.dumps(data)}\n\n"


async def _run_events(
    *,
    run_id: uuid.UUID,
    owner_id: uuid.UUID,
    request_id: str,
    poll_s: float = 0.1,
    heartbeat_s: float = 10.0,
) -> AsyncIterator[str]:
    """Yield SSE frames until the run terminates or disappears.

    Snapshot on connect, then one frame per observed change. Polling
    (rather than LISTEN/NOTIFY) keeps this working on any Postgres
    without extra extensions; step delivery is sequence-based so no
    step is ever skipped even if states coalesce between polls.

    Ownership is re-checked on every poll (not just the HTTP
    handshake) so a reassigned or deleted project closes the stream
    instead of leaking it (#016).
    """
    factory = get_session_factory()
    loop = asyncio.get_event_loop()
    last_state: RunState | None = None
    last_sequence = 0
    last_beat = loop.time()
    while True:
        session = factory()
        try:
            try:
                run = await service.get_owned_run(session, run_id, owner_id)
            except RunNotFoundError:
                yield _sse("error", {"code": "RESOURCE_NOT_FOUND"})
                return
            await session.refresh(run, attribute_names=["steps"])
            if last_state is None:
                yield _sse("snapshot", RunRead.model_validate(run).model_dump(mode="json"))
            else:
                if run.state != last_state:
                    yield _sse(
                        "state_changed",
                        {"state": run.state.value, "version": run.version},
                    )
                for step in run.steps:
                    if step.sequence > last_sequence:
                        yield _sse(
                            "step_added",
                            RunStepRead.model_validate(step).model_dump(mode="json"),
                        )
            last_state = run.state
            last_sequence = max([step.sequence for step in run.steps] + [last_sequence])
            if is_terminal_state(run.state):
                log.info(
                    "run_stream_closed",
                    run_id=str(run_id),
                    final_state=run.state.value,
                    request_id=request_id,
                )
                return
        finally:
            await session.close()
        if loop.time() - last_beat >= heartbeat_s:
            yield ": ping\n\n"
            last_beat = loop.time()
        await asyncio.sleep(poll_s)
