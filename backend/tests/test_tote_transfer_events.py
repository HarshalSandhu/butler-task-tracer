"""Ground-truth pick/drop events from htm_load_tote/htm_unload_tote order
+completion pairs, against a real capture (task
6227a076-190b-42dc-a957-f5523dbc2f94, bot 200) where the telemetry-plateau
merge alone silently absorbed the real drop action (htm_unload_tote,
height=420mm) into a longer surrounding descent -- it never appeared as its
own fork-adjustment event at all before this fix.
"""

from __future__ import annotations

import pathlib

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import build_fork_adjustment_events, build_lift_events, build_tote_transfer_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "tote_transfer_bot200.log"


def _load():
    return list(parse_lines(FIXTURE_PATH.read_text().splitlines()))


def test_detects_the_real_pick_and_drop():
    events = build_tote_transfer_events(_load())
    assert len(events) == 2
    assert [e.label for e in events] == ["pick", "drop"]


def test_pick_uses_real_order_height_and_completion_time():
    events = build_tote_transfer_events(_load())
    pick = events[0]
    assert pick.timestamp.strftime("%H:%M:%S.%f")[:-3] == "06:39:23.096"  # htm_load_tote_finished
    assert pick.to_height_mm == 880.0  # the order's own explicit height
    assert pick.direction == "up"


def test_drop_uses_real_order_height_and_completion_time():
    # This is the exact event that was previously missing entirely --
    # merged away into "lift down @ relay_storable_io_point (478->262)".
    events = build_tote_transfer_events(_load())
    drop = events[1]
    assert drop.timestamp.strftime("%H:%M:%S.%f")[:-3] == "06:41:39.559"  # htm_unload_tote_finished
    assert drop.to_height_mm == 420.0
    assert drop.from_height_mm == 478.0
    assert drop.direction == "down"


def test_combined_fork_adjustment_events_include_ground_truth_and_keep_the_prep_rise():
    # Real bug this locks in: a naive time-only dedup against the drop
    # event would also swallow the legitimate prep-rise (262->478mm) that
    # happens ~5s before the drop completes -- height-matching in the
    # dedup is what keeps them distinct.
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)

    labels_and_heights = [(e.label, e.from_height_mm, e.to_height_mm) for e in events]
    assert ("pick", 818.0, 880.0) in labels_and_heights
    assert ("drop", 478.0, 420.0) in labels_and_heights
    # the prep-rise before the drop must survive as its own event
    assert (None, 262.0, 478.0) in labels_and_heights


def test_no_events_when_no_load_unload_orders_present():
    assert build_tote_transfer_events([]) == []


def test_started_at_is_the_order_instant_and_coordinate_is_populated():
    events = build_tote_transfer_events(_load())
    pick, drop = events
    assert pick.started_at.strftime("%H:%M:%S.%f")[:-3] == "06:39:21.218"
    assert drop.started_at.strftime("%H:%M:%S.%f")[:-3] == "06:41:37.801"  # the htm_unload_tote order itself
    assert pick.coordinate is not None
    assert drop.coordinate is not None
