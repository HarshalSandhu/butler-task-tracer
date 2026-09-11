"""Ground-truth regression test: a real relay_group_task trace (VTM batching
totes 00000005/00000010/00000006 between storable and relay), captured the
same way as relay_pps_task_5fbc8f16.log.

Important real-world finding baked into these expectations, not a
simplification: grepping strictly by task_id (this task type's grep
strategy, same as relay_pps_task) only recovers lines that literally
restate the task's UUID. For relay_group_task specifically, most of its rich
per-tote subtask detail (load_tote/unload_tote/set_relay_group_task_status
transitions) does NOT restate the UUID inline -- only the movement lines,
the Starting/Processing/SubTask_list dispatch lines, and the
virtual_aisle_log_server summary lines do. Full subtask-level fidelity for
this type needs the correlation.py butler_id+time-window heuristic (not
built in this pass); this fixture and these tests reflect what's actually
recoverable via the plain task_id grep today.
"""

from __future__ import annotations

import pathlib

import pytest

from app.models import TaskStatus
from app.parsers.terminal_state import classify
from app.parsers.trace_builder import build_trace

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "relay_group_task_87510814.log"
TASK_ID = "87510814-d3da-465b-9a90-4e358056e293"


@pytest.fixture
def trace():
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    return build_trace(
        task_id=TASK_ID,
        task_type="relay_group_task",
        request_id=None,
        raw_lines=lines,
    )


def test_butler_id_resolved(trace):
    # Resolved from the Task={relay_group_task,<<...>>} field on the
    # goto_barcode_completed line, NOT MainTaskKey (which reads "undefined"
    # for this task type -- see relay_group_task.py docstring).
    assert trace.butler_id == "214"


def test_movement_events_resolved_from_task_field(trace):
    movement_events = [e for e in trace.events if e.attr_tag is not None]
    assert len(movement_events) == 4
    assert all(e.attr_tag == "ttp_storable_io_point" for e in movement_events)
    assert all(e.bot_id == "214" for e in movement_events)


def test_dispatched_at_from_subtask_list_line(trace):
    # First "TaskId: {...}, SubTask_list: [...]" line, 11:31:41.999.
    assert trace.dispatched_at is not None
    assert trace.dispatched_at.strftime("%H:%M:%S.%f")[:-3] == "11:31:41.999"


def test_no_created_at_marker_for_this_task_type(trace):
    # relay_group_task is MVTS-scheduled internally, not created via
    # transport_request_event_handler -- there is no "#Task created" line
    # for it, unlike relay_pps_task. created_at correctly stays None rather
    # than being guessed at.
    assert trace.created_at is None


def test_status_is_incomplete_not_falsely_failed(trace):
    # This is the regression this test file exists to guard: before the
    # terminal_state.py fix, the "Abandoning the current_subtask..." lines
    # (which fire here purely because the VTM is rescheduling onto its own
    # next tote-leg, twice in this fixture) made every relay_group_task
    # read FAILED. There's also no success terminal for this task type
    # (no "Delete Request with Task key" line), so INCOMPLETE is the
    # honest classification -- never silently "completed".
    assert trace.status == TaskStatus.INCOMPLETE


def test_self_referential_abandon_is_not_a_failure_signal():
    """Direct unit test of the classify() fix, independent of the fixture."""
    messages = [
        'Abandoning the current_subtask as there is new schedule with new task: {relay_group_task,<<"same-task">>}',
        "some other unrelated message",
    ]
    assert classify(messages, task_id="same-task") == TaskStatus.INCOMPLETE


def test_abandon_referencing_a_different_task_is_still_a_failure_signal():
    """The fix must not blanket-suppress the marker -- genuine preemption by
    a *different* task must still flag FAILED."""
    messages = [
        'Abandoning the current_subtask as there is new schedule with new task: {relay_group_task,<<"other-task">>}',
    ]
    assert classify(messages, task_id="same-task") == TaskStatus.FAILED


def test_classify_without_task_id_preserves_old_unconditional_behavior():
    """Backward compatibility: existing callers that don't pass task_id
    (e.g. any pre-existing test) must see identical behavior to before this
    fix -- the marker is always a failure signal in that mode."""
    messages = [
        'Abandoning the current_subtask as there is new schedule with new task: {relay_group_task,<<"whatever">>}',
    ]
    assert classify(messages) == TaskStatus.FAILED
