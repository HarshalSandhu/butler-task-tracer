"""api/routes.py's _maybe_reclassify_relay_group_completion -- fixes a real
gap where relay_group_task's own completion marker never restates the
task_id (see terminal_state.py's module docstring), so
terminal_state.classify() -- fed only the task_id-scoped grep by
build_trace() -- can never actually observe it in production, despite its
own regex matching correctly in isolation. Confirmed real: task
4e20786c-dec3-4545-b2ce-4948c1819f4e genuinely completed (its own
"set_relay_group_task_status,[complete]" line is in this fixture, at
14:36:03.699) but was reported INCOMPLETE before this fix, because that
line was never part of the task_id grep to begin with.
"""

from __future__ import annotations

import pathlib
from datetime import datetime

from app.api.routes import _maybe_reclassify_relay_group_completion
from app.models import TaskStatus, TaskTrace

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "vtm_relay_group_task_4e20786c.log"
TASK_ID = "4e20786c-dec3-4545-b2ce-4948c1819f4e"


def _incomplete_trace(task_type="relay_group_task") -> TaskTrace:
    return TaskTrace(
        request_id=None,
        task_id=TASK_ID,
        task_type=task_type,
        butler_id="214",
        status=TaskStatus.INCOMPLETE,
        # Real dispatched_at for this task -- the fixture's loose window
        # also contains the PRECEDING relay_group_task's own completion
        # (14:33:49.348, over a minute earlier on the same bot), which
        # dispatched_at is what lets the reclassify logic tell apart from
        # this task's own (14:36:03.699).
        dispatched_at=datetime(2026, 7, 29, 14, 34, 51, 412000),
    )


def test_reclassifies_to_completed_using_the_real_completion_line():
    trace = _incomplete_trace()
    raw_lift_lines = FIXTURE_PATH.read_text().splitlines()

    _maybe_reclassify_relay_group_completion(trace, raw_lift_lines)

    assert trace.status == TaskStatus.COMPLETED
    assert trace.completed_at == datetime(2026, 7, 29, 14, 36, 3, 699000)


def test_does_not_touch_an_already_completed_trace():
    trace = _incomplete_trace()
    trace.status = TaskStatus.COMPLETED
    trace.completed_at = datetime(2020, 1, 1)  # sentinel -- must survive untouched

    _maybe_reclassify_relay_group_completion(trace, FIXTURE_PATH.read_text().splitlines())

    assert trace.completed_at == datetime(2020, 1, 1)


def test_does_not_touch_a_failed_trace():
    trace = _incomplete_trace()
    trace.status = TaskStatus.FAILED

    _maybe_reclassify_relay_group_completion(trace, FIXTURE_PATH.read_text().splitlines())

    assert trace.status == TaskStatus.FAILED


def test_only_applies_to_relay_group_task():
    trace = _incomplete_trace(task_type="relay_pps_task")

    _maybe_reclassify_relay_group_completion(trace, FIXTURE_PATH.read_text().splitlines())

    assert trace.status == TaskStatus.INCOMPLETE


def test_stays_incomplete_when_no_completion_line_present():
    trace = _incomplete_trace()

    _maybe_reclassify_relay_group_completion(trace, [])

    assert trace.status == TaskStatus.INCOMPLETE
    assert trace.completed_at is None
