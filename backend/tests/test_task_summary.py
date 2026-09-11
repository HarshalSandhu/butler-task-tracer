"""Unit tests for parsers/task_summary.py's bulk scan correlation.

Line shapes below are copied verbatim (modulo timestamps/ids) from real
grep output against the validation VM for both anchor patterns -- see
task_summary.py's module docstring.
"""

from __future__ import annotations

from app.parsers.line_parser import parse_lines
from app.parsers.task_summary import build_task_summaries

_START_GROUP = (
    "2026-07-28 04:04:42.810 [debug][<0.17649.0>] --- rm_subtasks:handle_start_task_cast:"
    '{336,6}: butler_id=214 Starting TaskId: {relay_group_task,<<"g-task-1">>}'
)
_START_PPS = (
    "2026-07-28 04:32:30.465 [debug][<0.32650.0>] --- rm_subtasks:handle_start_task_cast:"
    '{336,6}: butler_id=210 Starting TaskId: {relay_pps_task,<<"p-task-1">>}'
)
_MOVEMENT_210 = (
    "2026-07-28 04:32:45.100 [debug][<0.32650.0>] --- rm_common_subtasks:goto_barcode_completed:"
    "{929,6}: butler_id=210 goto_barcode_completed: bot 210 reached {14,49} (attr=relay_pps)"
)
_MOVEMENT_214 = (
    "2026-07-28 04:05:10.200 [debug][<0.17649.0>] --- rm_common_subtasks:goto_barcode_completed:"
    "{929,6}: butler_id=214 goto_barcode_completed: bot 214 reached {10,20} (attr=relay_storable)"
)
_START_CHARGETASK = (
    "2026-07-24 11:14:17.496 [debug][<0.5644.0>] --- rm_subtasks:handle_start_task_cast:"
    '{336,6}: butler_id=206 Starting TaskId: {chargetask,<<"001d1a82-f75f-4c1d-9568-2dd5ba33ecfb">>}'
)
_MOVEMENT_206 = (
    "2026-07-24 11:14:48.716 [debug][<0.5644.0>] --- rm_common_subtasks:goto_barcode_completed:"
    "{929,6}: butler_id=206 goto_barcode_completed: bot 206 reached {506,506} (attr=charger_reinit)"
)
_START_PPS_SECOND = (
    "2026-07-28 04:40:00.000 [debug][<0.9999.0>] --- rm_subtasks:handle_start_task_cast:"
    '{336,6}: butler_id=210 Starting TaskId: {relay_pps_task,<<"p-task-2">>}'
)


def _summaries(*lines: str):
    return build_task_summaries(list(parse_lines(lines)))


def test_extracts_task_id_type_and_bot_from_start_line():
    summaries = _summaries(_START_GROUP)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.task_id == "g-task-1"
    assert s.task_type == "relay_group_task"
    assert s.bot_id == "214"
    assert s.relay_position is None


def test_attaches_relay_position_from_later_movement_on_same_bot():
    summaries = _summaries(_START_PPS, _MOVEMENT_210)
    assert summaries[0].relay_position == "relay_pps"
    assert summaries[0].last_seen_at is not None


def test_two_bots_do_not_cross_contaminate_relay_position():
    summaries = _summaries(_START_GROUP, _START_PPS, _MOVEMENT_210, _MOVEMENT_214)
    by_id = {s.task_id: s for s in summaries}
    assert by_id["g-task-1"].relay_position == "relay_storable"
    assert by_id["p-task-1"].relay_position == "relay_pps"


def test_order_independent_input_still_correlates_correctly():
    # Same lines, shuffled -- build_task_summaries must sort by timestamp
    # itself rather than trusting input order.
    summaries = _summaries(_MOVEMENT_214, _START_PPS, _MOVEMENT_210, _START_GROUP)
    by_id = {s.task_id: s for s in summaries}
    assert by_id["g-task-1"].relay_position == "relay_storable"
    assert by_id["p-task-1"].relay_position == "relay_pps"


def test_second_task_on_same_bot_marks_first_as_superseded():
    summaries = _summaries(_START_PPS, _MOVEMENT_210, _START_PPS_SECOND)
    by_id = {s.task_id: s for s in summaries}
    assert by_id["p-task-1"].is_bot_current_task is False
    assert by_id["p-task-2"].is_bot_current_task is True


def test_relay_group_task_self_reschedule_does_not_duplicate_row():
    # A VTM batching several totes re-emits "Starting TaskId" for the SAME
    # task_id once per tote leg -- must collapse to one row, not one per leg.
    restart = (
        "2026-07-28 04:06:00.000 [debug][<0.17649.0>] --- rm_subtasks:handle_start_task_cast:"
        '{336,6}: butler_id=214 Starting TaskId: {relay_group_task,<<"g-task-1">>}'
    )
    summaries = _summaries(_START_GROUP, _MOVEMENT_214, restart)
    assert len(summaries) == 1
    assert summaries[0].task_id == "g-task-1"
    assert summaries[0].created_at.second == 42  # keeps the FIRST occurrence's timestamp
    assert summaries[0].is_bot_current_task is True


def test_chargetask_recognized_with_relay_position_from_charger_reinit_attr():
    summaries = _summaries(_START_CHARGETASK, _MOVEMENT_206)
    assert len(summaries) == 1
    s = summaries[0]
    assert s.task_type == "chargetask"
    assert s.bot_id == "206"
    assert s.relay_position == "charger_reinit"


def test_movement_before_any_start_on_that_bot_is_ignored():
    # A movement line with no preceding "Starting TaskId" for that bot_id
    # can't be attributed to anything -- must not crash or attach it to an
    # unrelated task.
    summaries = _summaries(_MOVEMENT_210, _START_GROUP)
    assert len(summaries) == 1
    assert summaries[0].task_id == "g-task-1"
