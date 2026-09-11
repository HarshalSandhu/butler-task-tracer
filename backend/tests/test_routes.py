"""Unit tests for api/routes.py helpers that don't need a live SSH target."""

from __future__ import annotations

from datetime import datetime

from app.api.routes import _filter_lines_to_window, _sniff_task_type


def test_sniffs_relay_group_task_from_task_field():
    lines = [
        'goto_barcode_completed: bot 214 reached {11,51} (attr=ttp_storable_io_point), '
        'Task={relay_group_task,<<"87510814-d3da-465b-9a90-4e358056e293">>}, MainTaskKey=undefined'
    ]
    assert _sniff_task_type(lines, "87510814-d3da-465b-9a90-4e358056e293") == "relay_group_task"


def test_sniffs_relay_pps_task_from_taskid_field():
    lines = [
        'TaskId: {relay_pps_task,<<"5fbc8f16-3593-48d2-a7ac-c7cb3826949b">>}, SubTask_list: []'
    ]
    assert _sniff_task_type(lines, "5fbc8f16-3593-48d2-a7ac-c7cb3826949b") == "relay_pps_task"


def test_returns_none_when_type_never_appears_inline():
    assert _sniff_task_type(["some unrelated log line"], "some-task-id") is None


def test_does_not_raise_on_task_ids_containing_regex_metacharacters():
    """Regression: this previously crashed with `ValueError: unexpected '{'
    in field name` because the pattern was built with str.format(), which
    collides with the regex's own literal braces."""
    task_id = "weird.id+with*chars"
    lines = [f'Task={{relay_group_task,<<"{task_id}">>}}']
    assert _sniff_task_type(lines, task_id) == "relay_group_task"


def test_filter_lines_to_window_keeps_only_in_window_lines():
    lines = [
        "2026-08-04 09:59:00.000 [info][<0.1.0>] --- m:f:{1,1}: before window",
        "2026-08-04 10:00:00.000 [info][<0.1.0>] --- m:f:{1,1}: at window start",
        "2026-08-04 10:00:30.000 [info][<0.1.0>] --- m:f:{1,1}: inside window",
        "2026-08-04 10:01:00.000 [info][<0.1.0>] --- m:f:{1,1}: at window end",
        "2026-08-04 10:02:00.000 [info][<0.1.0>] --- m:f:{1,1}: after window",
    ]
    result = _filter_lines_to_window(lines, datetime(2026, 8, 4, 10, 0, 0), datetime(2026, 8, 4, 10, 1, 0))
    assert len(result) == 3
    assert "before window" not in "".join(result)
    assert "after window" not in "".join(result)


def test_filter_lines_to_window_keeps_unparseable_continuation_lines_of_a_kept_entry():
    # A multi-line ~p dump continuation has no timestamp of its own -- it
    # must be kept iff the entry it continues was itself in-window, never
    # silently dropped just because it doesn't match the lager line format.
    lines = [
        "2026-08-04 10:00:30.000 [info][<0.1.0>] --- m:f:{1,1}: entry with a dump",
        "    continuation line with no timestamp prefix",
        "2026-08-04 10:05:00.000 [info][<0.1.0>] --- m:f:{1,1}: out of window entry",
        "    this continuation belongs to the out-of-window entry",
    ]
    result = _filter_lines_to_window(lines, datetime(2026, 8, 4, 10, 0, 0), datetime(2026, 8, 4, 10, 1, 0))
    assert result == [
        "2026-08-04 10:00:30.000 [info][<0.1.0>] --- m:f:{1,1}: entry with a dump",
        "    continuation line with no timestamp prefix",
    ]
