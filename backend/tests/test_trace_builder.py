"""Ground-truth regression test: the real relay_pps_task trace captured and
manually verified during this tool's design session. If these numbers ever
drift, either the parser regressed or the fixture/expectations need
updating deliberately - never adjust the fixture to make a change pass.
"""

from __future__ import annotations

import pathlib

import pytest

from app.models import TaskStatus
from app.parsers.trace_builder import build_trace

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "relay_pps_task_5fbc8f16.log"
TASK_ID = "5fbc8f16-3593-48d2-a7ac-c7cb3826949b"
REQUEST_ID = "4899d0b6-0b3f-4e42-9afa-dacb61d1f39f"

# (from_attr, to_attr, expected_duration_seconds) - tolerance 0.05s for
# floating point / millisecond rounding, not for real drift.
EXPECTED_PHASES = [
    ("relay_storable_io_point", "relay_storable", 7.93),
    ("relay_storable", "relay_storable_io_point", 6.71),
    ("relay_storable_io_point", "pps_entry_queue", 41.14),
    ("pps_entry_queue", "pps", 77.04),
    ("pps", "pps", 63.61),
    ("pps", "highway", 11.35),
    ("highway", "relay_storable_io_point", 23.79),
    ("relay_storable_io_point", "relay_storable", 8.01),
    ("relay_storable", "relay_storable_io_point", 6.75),
]


@pytest.fixture
def trace():
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    return build_trace(
        task_id=TASK_ID,
        task_type="relay_pps_task",
        request_id=REQUEST_ID,
        raw_lines=lines,
    )


def test_status_is_completed(trace):
    assert trace.status == TaskStatus.COMPLETED


def test_butler_id_resolved(trace):
    assert trace.butler_id == "200"


def test_queued_duration(trace):
    # created 11:35:52.546, dispatched (started event) 11:39:31.478
    assert trace.queued_duration_seconds == pytest.approx(218.932, abs=0.01)


def test_total_duration(trace):
    assert trace.total_duration_seconds == pytest.approx(470.224, abs=0.01)


def test_phase_durations_match_manual_trace(trace):
    phases = trace.phase_durations()
    assert len(phases) == len(EXPECTED_PHASES)
    for actual, (from_attr, to_attr, expected_seconds) in zip(phases, EXPECTED_PHASES):
        assert actual["from_attr"] == from_attr
        assert actual["to_attr"] == to_attr
        assert actual["duration_seconds"] == pytest.approx(expected_seconds, abs=0.05)


def test_outbound_and_return_relay_legs_are_consistent(trace):
    """The nice internal-consistency check from the manual trace: the
    relay io<->storable legs on the way out and the way back should be
    close to each other, not wildly different - a sanity check on the
    parser's correctness, not just the exact numbers.
    """
    phases = trace.phase_durations()
    io_to_storable = [p for p in phases if p["from_attr"] == "relay_storable_io_point" and p["to_attr"] == "relay_storable"]
    storable_to_io = [p for p in phases if p["from_attr"] == "relay_storable" and p["to_attr"] == "relay_storable_io_point"]
    assert len(io_to_storable) == 2
    assert len(storable_to_io) == 2
    assert abs(io_to_storable[0]["duration_seconds"] - io_to_storable[1]["duration_seconds"]) < 0.5
    assert abs(storable_to_io[0]["duration_seconds"] - storable_to_io[1]["duration_seconds"]) < 0.5
