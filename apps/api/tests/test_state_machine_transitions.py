"""Exhaustive tests of the declarative Run state machine transition table.

These tests verify that ``app.runs.transitions.ALLOWED_TRANSITIONS``
mirrors ``docs/design/STATE_MACHINE_v0.1.md`` §4 verbatim.

Strategy
--------
We compute the *expected* table directly from the doc's transition rows
(via the helper :func:`_expected_transitions`). Any discrepancy between
the helper and the implementation is a contract violation, regardless of
which side is wrong.

These tests are deliberately pure (no database, no fixtures, no I/O).
They run in milliseconds and act as living documentation of the
contract.
"""

from __future__ import annotations

import pytest

from app.runs.enums import RunEvent, RunState, is_terminal_state
from app.runs.transitions import ALLOWED_TRANSITIONS, next_state


def _expected_transitions() -> dict[tuple[RunState, RunEvent], RunState]:
    """The transition table derived from STATE_MACHINE_v0.1.md §4.

    If you change this helper, you are changing the contract. Update the
    design doc in the same PR.
    """
    expected: dict[tuple[RunState, RunEvent], RunState] = {}

    # §4 explicit rows (forward path)
    expected[(RunState.CREATED, RunEvent.REPOSITORY_READY)] = RunState.ANALYZING
    expected[(RunState.ANALYZING, RunEvent.ANALYSIS_COMPLETE)] = RunState.PLANNING
    expected[(RunState.PLANNING, RunEvent.PLAN_READY)] = RunState.AWAITING_APPROVAL
    expected[(RunState.AWAITING_APPROVAL, RunEvent.PLAN_APPROVED)] = RunState.IMPLEMENTING
    expected[(RunState.AWAITING_APPROVAL, RunEvent.PLAN_REJECTED)] = RunState.PLANNING
    expected[(RunState.IMPLEMENTING, RunEvent.IMPLEMENTATION_COMPLETE)] = RunState.TESTING
    expected[(RunState.TESTING, RunEvent.TESTS_PASSED)] = RunState.REVIEWING
    expected[(RunState.TESTING, RunEvent.TESTS_FAILED)] = RunState.DEBUGGING
    expected[(RunState.DEBUGGING, RunEvent.FIX_READY)] = RunState.IMPLEMENTING
    expected[(RunState.REVIEWING, RunEvent.REVIEW_PASSED)] = RunState.COMPLETED

    # §4 cross-cutting rows ("any active" — we expand explicitly).
    # Active = non-terminal. NEEDS_HUMAN is included as an active state per
    # the doc's §9 ("a future API may allow NEEDS_HUMAN -> ...").
    active = (
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
    for src in active:
        expected[(src, RunEvent.CANCEL)] = RunState.CANCELLED
        expected[(src, RunEvent.ESCALATE)] = RunState.NEEDS_HUMAN
        expected[(src, RunEvent.UNRECOVERABLE_ERROR)] = RunState.FAILED

    return expected


def test_table_matches_state_machine_doc() -> None:
    """The full transition table matches STATE_MACHINE_v0.1.md §4."""
    assert ALLOWED_TRANSITIONS == _expected_transitions()


def test_every_state_has_at_least_one_event() -> None:
    """Every non-terminal state must have *some* outgoing transition.

    Otherwise the run is stuck. (Terminal states are excluded — they
    have zero outgoing transitions by definition.)
    """
    for state in RunState:
        if is_terminal_state(state):
            continue
        assert any(src == state for src, _ in ALLOWED_TRANSITIONS), (
            f"State {state.value} has no outgoing transitions"
        )


def test_every_event_is_used_at_least_once() -> None:
    """Every event in the enum appears in at least one transition.

    Catches dead enum members — they probably should not exist.
    """
    used_events = {event for _, event in ALLOWED_TRANSITIONS}
    for event in RunEvent:
        assert event in used_events, f"Event {event.value} is never used"


def test_no_transitions_from_terminal_states() -> None:
    """Terminal states have no outgoing transitions.

    A future "resume" transition from NEEDS_HUMAN would belong in a new
    state machine doc version, not in this issue.
    """
    for (src, _event), _dst in ALLOWED_TRANSITIONS.items():
        assert not is_terminal_state(src), (
            f"Terminal state {src.value} should not appear in the transition table"
        )


def test_terminal_states_are_terminal_per_doc() -> None:
    """Per STATE_MACHINE §10, terminal states are COMPLETED/FAILED/CANCELLED.

    NEEDS_HUMAN is paused, not terminal.
    """
    assert is_terminal_state(RunState.COMPLETED)
    assert is_terminal_state(RunState.FAILED)
    assert is_terminal_state(RunState.CANCELLED)
    assert not is_terminal_state(RunState.NEEDS_HUMAN)


@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        # Forward path
        (RunState.CREATED, RunEvent.REPOSITORY_READY, RunState.ANALYZING),
        (RunState.ANALYZING, RunEvent.ANALYSIS_COMPLETE, RunState.PLANNING),
        (RunState.PLANNING, RunEvent.PLAN_READY, RunState.AWAITING_APPROVAL),
        (RunState.AWAITING_APPROVAL, RunEvent.PLAN_APPROVED, RunState.IMPLEMENTING),
        (RunState.AWAITING_APPROVAL, RunEvent.PLAN_REJECTED, RunState.PLANNING),
        (RunState.IMPLEMENTING, RunEvent.IMPLEMENTATION_COMPLETE, RunState.TESTING),
        (RunState.TESTING, RunEvent.TESTS_PASSED, RunState.REVIEWING),
        (RunState.TESTING, RunEvent.TESTS_FAILED, RunState.DEBUGGING),
        (RunState.DEBUGGING, RunEvent.FIX_READY, RunState.IMPLEMENTING),
        (RunState.REVIEWING, RunEvent.REVIEW_PASSED, RunState.COMPLETED),
        # Cross-cutting
        (RunState.CREATED, RunEvent.CANCEL, RunState.CANCELLED),
        (RunState.ANALYZING, RunEvent.ESCALATE, RunState.NEEDS_HUMAN),
        (RunState.IMPLEMENTING, RunEvent.UNRECOVERABLE_ERROR, RunState.FAILED),
        (RunState.NEEDS_HUMAN, RunEvent.CANCEL, RunState.CANCELLED),
    ],
)
def test_next_state_explicit_rows(current: RunState, event: RunEvent, expected: RunState) -> None:
    assert next_state(current, event) == expected


@pytest.mark.parametrize(
    "current",
    [
        RunState.CREATED,
        RunState.ANALYZING,
        RunState.IMPLEMENTING,
        RunState.TESTING,
        RunState.REVIEWING,
        RunState.NEEDS_HUMAN,
    ],
)
def test_invalid_event_from_state_is_rejected(current: RunState) -> None:
    """At least one known event must be invalid from every active state.

    We pick an event that the doc never pairs with this state.
    """
    # TESTS_FAILED is only valid from TESTING.
    if current is RunState.TESTING:
        return
    with pytest.raises(KeyError):
        next_state(current, RunEvent.TESTS_FAILED)
