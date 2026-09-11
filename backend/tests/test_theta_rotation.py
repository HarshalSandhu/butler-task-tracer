"""Ground-truth rotation reconstruction from the AGV's own reported heading
(agvPosition.theta), against a real capture (bot 210, task
ef3d2ee1-c0e7-498e-9824-c32f34a3c7a3's highway -> relay_storable_io_point
leg) -- see rotation_events.py's module docstring for why this is preferred
over the turn_step planned-path estimate.
"""

from __future__ import annotations

import pathlib
from datetime import datetime

import pytest

from app.parsers.line_parser import parse_lines
from app.parsers.rotation_events import (
    build_rotation_events,
    build_theta_rotation_events,
    parse_theta_telemetry,
)

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "theta_telemetry_bot210.log"


def _load():
    return list(parse_lines(FIXTURE_PATH.read_text().splitlines()))


def test_parses_theta_readings_for_the_right_bot():
    telemetry = parse_theta_telemetry(_load())
    assert list(telemetry.keys()) == ["210"]
    assert len(telemetry["210"]) == 69


def test_detects_four_real_rotations_not_sensor_noise():
    telemetry = parse_theta_telemetry(_load())
    events = build_theta_rotation_events(telemetry["210"], "210")
    # Real theta sequence: 0.0 (held) -> 1.57 (held) -> 0.0 (held) -> 1.57
    # (held) -> 0.0 (held) -- 4 real transitions, not one per noisy reading.
    assert len(events) == 4
    assert [round(e.duration_ms) for e in events] == [1339, 2343, 1675, 2107]


def test_theta_events_have_a_real_coordinate_and_are_telemetry_method():
    telemetry = parse_theta_telemetry(_load())
    events = build_theta_rotation_events(telemetry["210"], "210")
    assert all(e.coordinate is not None for e in events)
    assert all(e.method == "telemetry" for e in events)
    assert all(e.confidence.value == "heuristic" for e in events)


def test_build_rotation_events_includes_theta_events_via_the_combined_entrypoint():
    events = build_rotation_events(_load())
    assert len(events) == 4
    assert all(e.method == "telemetry" for e in events)


def test_turn_step_estimate_confirmed_by_nearby_telemetry_is_dropped():
    # A synthetic turn_step estimate landing within the confirm window of a
    # real telemetry rotation (13:58:53.520) must not also appear as a
    # second, redundant row for the same physical turn.
    synthetic_turn_step = (
        "2026-07-28 13:58:52.000 [debug][<0.331834.0>] --- navigator_agent:handle_event:{2183,6}: "
        "butler_id=210 Got goal pathlist = [{coordinate_movement_info,{21,68},100,100,100,100,"
        "[{span,butler,{21,68}}],{21,68},{21,68},north,undefined,0,turn_step,0,undefined,north,false,1}]"
    )
    lines = _load() + list(parse_lines([synthetic_turn_step]))
    events = build_rotation_events(lines)
    # Still 4 -- the synthetic estimate (within 5s of 13:58:53.520) is dropped.
    assert len(events) == 4
    assert all(e.method == "telemetry" for e in events)


def test_sparse_telemetry_gap_during_a_long_idle_period_is_not_a_rotation():
    # Real bug confirmed against a real chargetask trace (VTM bot 214,
    # 165500f6-d46e-43f6-8fa6-ee1d7c691a45): during the ~8-minute charging
    # pause, telemetry sampling goes sparse, so two consecutive readings
    # can be minutes apart -- if the heading also differs between them,
    # that gap was previously misread as one continuous multi-minute
    # "rotation" (real captured examples: 838964ms and 627713ms). A held
    # heading, then a change after a long gap, must be capped out rather
    # than reported as a ~14-minute turn.
    readings = [
        (datetime(2026, 7, 28, 8, 41, 29), 0.0, 10.0, 20.0),
        (datetime(2026, 7, 28, 8, 55, 8), 1.57, 10.0, 20.0),  # ~14 minutes later
    ]
    events = build_theta_rotation_events(readings, "214")
    assert events == []


def test_a_real_short_rotation_still_passes_the_cap():
    readings = [
        (datetime(2026, 7, 28, 8, 41, 29, 0), 0.0, 10.0, 20.0),
        (datetime(2026, 7, 28, 8, 41, 31, 500000), 1.57, 10.0, 20.0),  # 2.5s, a real turn
    ]
    events = build_theta_rotation_events(readings, "214")
    assert len(events) == 1
    assert events[0].duration_ms == pytest.approx(2500.0, abs=1.0)
    assert events[0].coordinate == (10.0, 20.0)


def test_turn_step_estimate_far_from_any_telemetry_is_kept():
    # A turn_step far outside the fixture's telemetry window (no nearby
    # confirmation) must survive as a fallback estimate.
    far_turn_step = (
        "2026-07-28 14:05:00.000 [debug][<0.331834.0>] --- navigator_agent:handle_event:{2183,6}: "
        "butler_id=210 Got goal pathlist = [{coordinate_movement_info,{30,30},100,100,100,2100,"
        "[{span,butler,{30,30}}],{30,30},{30,30},north,undefined,0,turn_step,0,undefined,north,false,1}]"
    )
    lines = _load() + list(parse_lines([far_turn_step]))
    events = build_rotation_events(lines)
    assert len(events) == 5
    kept = [e for e in events if e.method == "planned_path_estimate"]
    assert len(kept) == 1
    assert kept[0].coordinate == (30, 30)
