"""Declarative Run state machine transition table.

This module is the Python mirror of ``docs/design/STATE_MACHINE_v0.1.md``
§4. Every row of the doc's transition table is encoded as an
``ALLOWED_TRANSITIONS[(from_state, event)] = to_state`` mapping. The unit
test in ``tests/test_state_machine_transitions.py`` iterates over the full
table and asserts every row is present and only those rows are allowed.

Keeping the transition table declarative (a Python dict) instead of
encoded in the database means:

  * The contract is reviewable in a single diff.
  * Adding a transition requires a code change, which is reviewable.
  * Tests can iterate the table without a database.

If a future requirement demands runtime edits (e.g. tenant-specific
workflows), this dict should be moved to the database and loaded at
startup, with the schema treated as a contract.
"""
from __future__ import annotations

from app.runs.enums import RunEvent, RunState


# Build the table from STATE_MACHINE_v0.1.md §4 verbatim. Each row is
# keyed by ``(from_state, event)`` and yields the destination state.
#
# "Any active" rows (cancel/escalate/unrecoverable_error) are expanded
# into one explicit entry per *non-terminal* active state. NEEDS_HUMAN is
# included as a source because, while it is paused, a user CAN still cancel
# or escalate from it (see STATE_MACHINE §9 — "a future API may allow
# NEEDS_HUMAN → IMPLEMENTING / PLANNING"). In this issue we implement only
# the cancel/escalate/unrecoverable_error escape hatches from NEEDS_HUMAN;
# the resume transitions belong to a later issue.
def _build_table() -> dict[tuple[RunState, RunEvent], RunState]:
    transitions: dict[tuple[RunState, RunEvent], RunState] = {}

    # ----- Forward path (§4 explicit rows) -----
    transitions[(RunState.CREATED, RunEvent.REPOSITORY_READY)] = RunState.ANALYZING
    transitions[(RunState.ANALYZING, RunEvent.ANALYSIS_COMPLETE)] = RunState.PLANNING
    transitions[(RunState.PLANNING, RunEvent.PLAN_READY)] = RunState.AWAITING_APPROVAL
    transitions[(RunState.AWAITING_APPROVAL, RunEvent.PLAN_APPROVED)] = RunState.IMPLEMENTING
    transitions[(RunState.AWAITING_APPROVAL, RunEvent.PLAN_REJECTED)] = RunState.PLANNING
    transitions[(RunState.IMPLEMENTING, RunEvent.IMPLEMENTATION_COMPLETE)] = RunState.TESTING
    transitions[(RunState.TESTING, RunEvent.TESTS_PASSED)] = RunState.REVIEWING
    transitions[(RunState.TESTING, RunEvent.TESTS_FAILED)] = RunState.DEBUGGING
    transitions[(RunState.DEBUGGING, RunEvent.FIX_READY)] = RunState.IMPLEMENTING
    transitions[(RunState.REVIEWING, RunEvent.REVIEW_PASSED)] = RunState.COMPLETED

    # ----- Cross-cutting: cancel / escalate / unrecoverable_error -----
    # "Any active" in §4 means any state from which work is still in flight.
    # We expand it explicitly so the table can be exhaustively tested.
    active_states: tuple[RunState, ...] = (
        RunState.CREATED,
        RunState.ANALYZING,
        RunState.PLANNING,
        RunState.AWAITING_APPROVAL,
        RunState.IMPLEMENTING,
        RunState.TESTING,
        RunState.DEBUGGING,
        RunState.REVIEWING,
        RunState.NEEDS_HUMAN,
    )
    for src in active_states:
        transitions[(src, RunEvent.CANCEL)] = RunState.CANCELLED
        transitions[(src, RunEvent.ESCALATE)] = RunState.NEEDS_HUMAN
        transitions[(src, RunEvent.UNRECOVERABLE_ERROR)] = RunState.FAILED

    return transitions


ALLOWED_TRANSITIONS: dict[tuple[RunState, RunEvent], RunState] = _build_table()


def next_state(current: RunState, event: RunEvent) -> RunState:
    """Return the destination state for ``(current, event)``.

    Raises:
        KeyError: if ``(current, event)`` is not in ``ALLOWED_TRANSITIONS``.
                  Callers should translate this into the appropriate typed
                  exception (``UnknownEventError`` vs ``InvalidTransitionError``)
                  — see :mod:`app.runs.errors` and :mod:`app.runs.service`.
    """
    return ALLOWED_TRANSITIONS[(current, event)]


__all__ = ["ALLOWED_TRANSITIONS", "next_state"]
