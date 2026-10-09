"""Structured logging for the execution worker.

Mirrors the API's logging configuration. JSON in non-development, pretty
console output in development.
"""

from __future__ import annotations

import io
import logging
import sys
from typing import TextIO, cast

import structlog
from structlog.typing import Processor

from forge_worker.config import Settings


class _DynamicStdout(io.TextIOBase):
    """File-like proxy resolving ``sys.stdout`` on each write.

    Binding ``sys.stdout`` at configure time captures a handle that
    pytest's capture can close under later tests, crashing subsequent
    log calls (Issue #85). Re-resolving per write is cheap and avoids
    that, in both structlog and the stdlib handler.
    """

    def write(self, message: str) -> int:
        return sys.stdout.write(message)

    def flush(self) -> None:
        sys.stdout.flush()


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_development:
        processors: list[Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.processors.EventRenamer("event"),
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        # structlog types `file` as TextIO; the proxy is file-like
        # (write/flush) without inheriting the whole ABC (Issue #85).
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, _DynamicStdout())),
        # Caching the logger captures the file handle at first use. That
        # interacts poorly with pytest's stdout capture, which closes
        # the original handle. Re-resolving the writer on each call is
        # cheap and avoids that.
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(stream=_DynamicStdout())
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return cast(structlog.stdlib.BoundLogger, logger)
