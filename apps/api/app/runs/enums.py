"""Run state and event enums.

These enums mirror ``docs/design/STATE_MACHINE_v0.1.md`` §2 (states) and §4
(events that drive transitions). They are the single source of truth in
Python: the Postgres ``run_state`` enum in
``db/migrations/0002_runs_and_run_steps.sql`` and the transition table in
:mod:`app.runs.transitions` both reference the same string values.

Changing a value here is a contract change. Open a doc-bump issue and add a
new ``_v0.2`` state-machine document; do not silently rename.
"""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    """States from STATE_MACHINE_v0.1.md §2."""

    CREATED = "CREATED"
    ANALYZING = "ANALYZING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    DEBUGGING = "DEBUGGING"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    NEEDS_HUMAN = "NEEDS_HUMAN"


# Terminal states per STATE_MACHINE_v0.1.md §10. NEEDS_HUMAN is intentionally
# excluded: it is operationally paused, not permanently terminal, and the doc
# notes that a future API may resume from it.
_TERMINAL_STATES: frozenset[RunState] = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)


def is_terminal_state(state: RunState) -> bool:
    """True for states from which no further transitions are possible."""
    return state in _TERMINAL_STATES


class RunEvent(str, Enum):
    """Events from STATE_MACHINE_v0.1.md §4 (transition table)."""

    # Forward path
    REPOSITORY_READY = "repository_ready"
    ANALYSIS_COMPLETE = "analysis_complete"
    PLAN_READY = "plan_ready"
    PLAN_APPROVED = "plan_approved"
    PLAN_REJECTED = "plan_rejected"
    IMPLEMENTATION_COMPLETE = "implementation_complete"
    TESTS_PASSED = "tests_passed"
    TESTS_FAILED = "tests_failed"
    FIX_READY = "fix_ready"
    REVIEW_PASSED = "review_passed"

    # Cross-cutting
    CANCEL = "cancel"
    ESCALATE = "escalate"
    UNRECOVERABLE_ERROR = "unrecoverable_error"
