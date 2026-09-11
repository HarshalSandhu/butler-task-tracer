"""Generic, format-agnostic movement/phase recovery (parsers/
generic_movement.py) -- against a real capture (task
d0461a46-a3b2-4f64-803f-9ab55bf77f8e, bot 134, a differently-versioned
server at 192.168.234.14) where the task type's own EXACT movement
resolver (task_types/relay_pps_task.py's goto_barcode_completed regex)
finds NOTHING at all: this version logs arrivals via
`navigator_agent:reached_destination` instead -- a raw {x,y} coordinate
with no semantic attr label, no task_id, no MainTaskKey. Confirmed real via
direct SSH before this module existed: butler_id/phases/events were ALL
empty for this task.
"""

from __future__ import annotations

import pathlib

from app.parsers.generic_movement import (
    build_generic_movement_events,
    extract_butler_id,
    extract_waypoint_labels,
)
from app.parsers.line_parser import parse_lines
from app.parsers.trace_builder import build_trace

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
TASK_LINES = (FIXTURES / "relay_pps_task_d0461a46_78format.log").read_text().splitlines(keepends=True)
ROTATION_LINES = (FIXTURES / "rotation_bot134_78format.log").read_text().splitlines()
TASK_ID = "d0461a46-a3b2-4f64-803f-9ab55bf77f8e"


def test_exact_resolver_finds_nothing_for_this_capture():
    # Sanity check that this fixture genuinely exercises the fallback --
    # if the exact resolver ever started matching here, the fallback
    # wouldn't be exercised by this test at all.
    trace = build_trace(task_id=TASK_ID, task_type="relay_pps_task", request_id=None, raw_lines=TASK_LINES)
    assert trace.phase_durations() == []


def test_extract_butler_id_is_format_agnostic():
    assert extract_butler_id(TASK_LINES) == "134"


def test_extract_butler_id_none_when_no_lines_have_it():
    assert extract_butler_id(["not a real log line"]) is None


def test_extracts_all_three_real_waypoint_labels():
    labels = extract_waypoint_labels(TASK_LINES)
    # {48,168}/{48,165} (the exit-queue leg) has a target_coord_with_dir
    # but no destination_info anywhere in this trace -- correctly absent,
    # not fabricated.
    assert labels == {
        (108, 41): "relay_storable",  # pickup, TLOC_0015918
        (47, 168): "pps",  # pps_id 130
        (15, 45): "relay_storable",  # drop, TLOC_0015320 -- only ever
        # stated in a later "Current SubTask" line, not the upfront dump
    }


def test_builds_real_movement_events_from_reached_destination_lines():
    labels = extract_waypoint_labels(TASK_LINES)
    parsed = list(parse_lines(ROTATION_LINES))
    events = build_generic_movement_events(parsed, labels)

    assert len(events) > 0
    assert all(e.bot_id == "134" for e in events)
    assert all(e.confidence.value == "heuristic" for e in events)
    # Every recovered event's attr must be one of the 3 real resolved
    # waypoints -- never a fabricated label for an unresolved coordinate.
    assert all(e.attr_tag in {"relay_storable", "pps"} for e in events)
    # Real, known-good arrival: the pickup at {108,41}.
    pickup = [e for e in events if e.timestamp.strftime("%H:%M:%S.%f")[:-3] == "09:50:28.896"]
    assert len(pickup) == 1
    assert pickup[0].attr_tag == "relay_storable"


def test_unresolved_coordinate_produces_no_event():
    # {48,168}/{48,165} (exit queue) has no destination_info -- confirm no
    # event is fabricated for it even though reached_destination lines at
    # that coordinate do exist in the raw capture.
    labels = extract_waypoint_labels(TASK_LINES)
    assert (48, 168) not in labels
    parsed = list(parse_lines(ROTATION_LINES))
    events = build_generic_movement_events(parsed, labels)
    assert not any(e.raw_line and "{{{48,168}" in e.raw_line for e in events)


def test_full_pipeline_recovers_real_phases():
    trace = build_trace(task_id=TASK_ID, task_type="relay_pps_task", request_id=None, raw_lines=TASK_LINES)
    assert trace.butler_id == "134"

    labels = extract_waypoint_labels(TASK_LINES)
    parsed = list(parse_lines(ROTATION_LINES))
    new_events = build_generic_movement_events(parsed, labels)
    trace.events = sorted(trace.events + new_events, key=lambda e: e.timestamp)

    phases = trace.phase_durations()
    assert len(phases) > 0
    attrs_seen = {p["to_attr"] for p in phases}
    assert attrs_seen == {"relay_storable", "pps"}
