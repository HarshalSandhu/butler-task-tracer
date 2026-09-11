"""Ground-truth regression test against a second real relay_pps_task trace
(70f0fa18..., captured and analyzed this session) that specifically covers
what the 5fbc8f16 fixture doesn't: a task that completes cleanly WITHOUT
ever logging "#Task created" (so created_at is None), which is exactly the
case cycle_duration_seconds exists to handle -- see models.py's docstring.
"""

from __future__ import annotations

import pathlib

import pytest

from app.models import TaskStatus
from app.parsers.trace_builder import build_trace

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "relay_pps_task_70f0fa18.log"
TASK_ID = "70f0fa18-c9d9-4992-b209-0225654bf05f"


@pytest.fixture
def trace():
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    return build_trace(task_id=TASK_ID, task_type="relay_pps_task", request_id=None, raw_lines=lines)


def test_status_completed_via_its_own_completion_marker(trace):
    assert trace.status == TaskStatus.COMPLETED


def test_created_at_is_none_but_cycle_duration_still_works(trace):
    # This task never logs "#Task created" -- confirmed real gap that
    # total_duration_seconds can't cover, which is exactly why
    # cycle_duration_seconds (dispatched_at-based) exists.
    assert trace.created_at is None
    assert trace.total_duration_seconds is None
    assert trace.cycle_duration_seconds == pytest.approx(120.755, abs=0.01)


def test_tote_id_extracted():
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    trace = build_trace(task_id=TASK_ID, task_type="relay_pps_task", request_id=None, raw_lines=lines)
    assert trace.tote_ids == ["00000009"]


def test_no_warnings_or_errors_in_a_clean_run(trace):
    assert trace.has_warnings_or_errors is False
    assert trace.warning_lines == []


def test_warning_line_is_surfaced_when_present():
    # Synthetic warning line spliced into the real fixture (this exact
    # task's own real capture had none) to verify the detection path itself.
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    lines.insert(
        5,
        "2026-07-28 14:32:40.000 [warning][<0.331851.0>] --- rm_subtasks:process_internal:{300,6}: "
        "butler_id=210 retrying goto_barcode after a transient navigation stall\n",
    )
    trace = build_trace(task_id=TASK_ID, task_type="relay_pps_task", request_id=None, raw_lines=lines)
    assert trace.has_warnings_or_errors is True
    assert len(trace.warning_lines) == 1
    assert "[warning]" in trace.warning_lines[0]
