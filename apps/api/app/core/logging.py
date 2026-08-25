"""Structured logging foundation for the Forge API.

Uses `structlog` to produce JSON logs in non-development environments and
human-friendly console logs during local development. The contract matches
`docs/operations/OBSERVABILITY_v0.1.md`:

- Every log line is a JSON object with: timestamp, level, service, event,
  and any project/run/trace correlation fields the caller supplies.
- Secrets must never be passed into the logger.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

import structlog

from app.config import Settings

# Bound loggers carry correlation context (request_id, run_id, project_id, ...).
LogContext = dict[str, Any]


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog for the whole process.

    Safe to call multiple times — the last call wins.
    """
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Reset any existing handlers (e.g. uvicorn's defaults) so our format
    # is the single source of truth.
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream=sys.stdout)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_development:
        # Pretty, colored output for local dev.
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # JSON for everything else.
        processors = [
            *shared_processors,
            structlog.processors.EventRenamer("event"),
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        # Caching the logger captures the file handle at first use. That
        # interacts poorly with pytest's stdout capture, which closes
        # the original handle. Re-resolving the writer on each call is
        # cheap and avoids that.
        cache_logger_on_first_use=False,
    )

    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn uses its own loggers; align their level with ours so that
    # access logs etc. follow the same filter.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger.

    Usage:
        log = get_logger(__name__)
        log.info("api_started", port=settings.api_port)
    """
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return cast(structlog.stdlib.BoundLogger, logger)
