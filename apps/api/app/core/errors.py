"""Error envelope and exception handlers.

The error format matches `docs/api/OPENAPI_v0.1.md`:

    {
      "error": {
        "code": "RUN_NOT_FOUND",
        "message": "Run does not exist.",
        "request_id": "req_123"
      }
    }

The application must never leak stack traces, secrets, internal prompts, or
provider credentials in error responses.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger(__name__)


def _request_id(request: Request) -> str:
    return (
        request.headers.get("x-request-id")
        or request.headers.get("X-Request-ID")
        or f"req_{uuid.uuid4().hex[:16]}"
    )


def error_payload(*, code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


def install_exception_handlers(app: FastAPI) -> None:
    """Register the standard error handlers on `app`."""

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next: Any) -> Any:
        request_id = _request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            400: "VALIDATION_ERROR",
            401: "AUTHENTICATION_ERROR",
            403: "AUTHORIZATION_ERROR",
            404: "RESOURCE_NOT_FOUND",
            409: "CONFLICT",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "INTERNAL_ERROR")
        message = str(exc.detail) if exc.detail else "Request failed."
        log.warning(
            "http_exception",
            status_code=exc.status_code,
            code=code,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code=code,
                message=message,
                request_id=request.state.request_id,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        log.info(
            "validation_error",
            path=request.url.path,
            errors=exc.errors(),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_payload(
                code="VALIDATION_ERROR",
                message="Request validation failed.",
                request_id=request.state.request_id,
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak the exception details. Log them server-side instead.
        log.error(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_payload(
                code="INTERNAL_ERROR",
                message="An internal error occurred.",
                request_id=request.state.request_id,
            ),
        )
