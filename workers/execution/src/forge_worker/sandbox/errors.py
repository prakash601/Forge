"""Structured errors for workspace tool calls.

Every failure carries a stable machine-readable ``code`` (per
``TOOL_CONTRACTS`` §11 and ``LLD`` §54) so agents and tests can reason
about it. The orchestrator owns retry policy; the executor only
reports.
"""

from __future__ import annotations

PATH_OUTSIDE_WORKSPACE = "PATH_OUTSIDE_WORKSPACE"
FILE_NOT_FOUND = "FILE_NOT_FOUND"
FILE_TOO_LARGE = "FILE_TOO_LARGE"
BINARY_FILE = "BINARY_FILE"
PROTECTED_PATH = "PROTECTED_PATH"
EDIT_NO_MATCH = "EDIT_NO_MATCH"
EDIT_AMBIGUOUS = "EDIT_AMBIGUOUS"
INVALID_INPUT = "INVALID_INPUT"
COMMAND_NOT_ALLOWED = "COMMAND_NOT_ALLOWED"
SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
GIT_OPERATION_FAILED = "GIT_OPERATION_FAILED"
WORKSPACE_EXISTS = "WORKSPACE_EXISTS"
INVALID_RUN_ID = "INVALID_RUN_ID"


class ToolError(Exception):
    """A tool call that failed validation or execution.

    Attributes:
        code: stable error code from this module.
        message: human-readable detail (safe to surface to agents).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = [
    "BINARY_FILE",
    "COMMAND_NOT_ALLOWED",
    "EDIT_AMBIGUOUS",
    "EDIT_NO_MATCH",
    "FILE_NOT_FOUND",
    "FILE_TOO_LARGE",
    "GIT_OPERATION_FAILED",
    "INVALID_INPUT",
    "INVALID_RUN_ID",
    "PATH_OUTSIDE_WORKSPACE",
    "PROTECTED_PATH",
    "SANDBOX_TIMEOUT",
    "TOOL_EXECUTION_FAILED",
    "WORKSPACE_EXISTS",
    "ToolError",
]
