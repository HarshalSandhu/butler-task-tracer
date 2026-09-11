"""Fork height adjustments visible in AGV telemetry that aren't already
captured as a LiftEvent -- e.g. set_fork_height_to_entry_height_without_tote
/set_fork_height_to_htm_bot_for_pps -- against a real, full telemetry
capture for task 70f0fa18-c9d9-4992-b209-0225654bf05f (bot 210).

Ground truth for these 4 real transitions (manually verified against the
fixture): rise before pickup (252->478mm), rise before the PPS handoff
(252->548mm), rise on the return leg back to relay_storable_io_point
(252->478mm -- this is the "4th" fork movement that has no corresponding
simultaneousForkLift order at all, since this task's own SubTask_list only
ever dispatches 3), and the final settle back down (478->252mm).
"""

from __future__ import annotations

import pathlib

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import build_fork_adjustment_events, build_lift_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "lift_telemetry_70f0fa18.log"


def _load():
    return list(parse_lines(FIXTURE_PATH.read_text().splitlines()))


def test_detects_four_real_fork_adjustments():
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)
    assert len(events) == 4
    assert [e.direction for e in events] == ["up", "up", "up", "down"]
    assert [(round(e.from_height_mm), round(e.to_height_mm)) for e in events] == [
        (252, 478),
        (252, 548),
        (252, 478),
        (478, 252),
    ]


def test_does_not_duplicate_transitions_already_shown_as_lift_events():
    # The 2 real down-transitions (478->252, 548->252) both coincide with
    # this task's own simultaneousForkLift LiftEvents -- must not also
    # appear as separate fork-adjustment rows.
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)
    down_events = [e for e in events if e.direction == "down"]
    assert len(down_events) == 1  # only the final untracked settle, not the 2 already-covered drops


def test_without_existing_lift_events_the_covered_drops_reappear():
    # Sanity check that dedup is actually doing something -- with no
    # existing LiftEvents to dedup against, all 6 real transitions show up
    # (including the 2 that build_lift_events already covers elsewhere).
    parsed = _load()
    events = build_fork_adjustment_events(parsed, [])
    assert len(events) == 6


def test_events_are_confidence_heuristic_with_no_label_yet():
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)
    assert all(e.confidence.value == "heuristic" for e in events)
    assert all(e.label is None for e in events)  # event_context.py fills this in


def test_started_at_is_at_or_before_the_settle_timestamp_and_coordinate_is_populated():
    # started_at is the earliest telemetry evidence the fork left its old
    # height -- necessarily at/before `timestamp` (when it settled at the
    # new one). Real values for this fixture (verified against the raw
    # telemetry): the pickup rise (252->478 @ 14:33:01.976) actually started
    # ~10.4s earlier, at 14:32:51.539 -- a real, evidenced gap, not a
    # rounding artifact.
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)
    assert all(e.started_at is not None for e in events)
    assert all(e.started_at <= e.timestamp for e in events)
    assert all(e.coordinate is not None for e in events)
    pickup_rise = events[0]
    assert pickup_rise.started_at.strftime("%H:%M:%S.%f")[:-3] == "14:32:51.539"
