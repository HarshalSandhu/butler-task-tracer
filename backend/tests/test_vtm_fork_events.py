"""VTM's fork-height/tote-transfer vocabulary -- against a real capture
(task 4e20786c-dec3-4545-b2ce-4948c1819f4e, bot 214): `setForkHeight`
(VTM's simultaneous-lift equivalent to HTM's simultaneousForkLift) and
`tote_load`/`tote_unload` (VTM's ground-truth pick/drop, equivalent to
HTM's htm_load_tote/htm_unload_tote).

Ground truth for this trace (manually verified against the raw telemetry
and the VDA5050 actionStates stream -- see the session's own investigation
notes): 2 tote transfers (load {11,47}->unload {11,58}, then load {11,51}
->unload {11,54}), each preceded by a `setForkHeight` order that
pre-positions the fork WHILE THE BOT IS STILL TRAVELING to the next
waypoint -- confirmed real: the first setForkHeight order (target 1300mm)
is acked (actionStatus=FINISHED) at 14:34:52.381, but liftHeight telemetry
doesn't cross within tolerance of 1300mm until 14:34:55.175, ~2.8s later.
"""

from __future__ import annotations

import pathlib

import pytest

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import build_fork_adjustment_events, build_lift_events, build_tote_transfer_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "vtm_relay_group_task_4e20786c.log"


def _load():
    return list(parse_lines(FIXTURE_PATH.read_text().splitlines()))


def test_detects_both_setforkheight_simultaneous_lifts():
    events = build_lift_events(_load())
    assert len(events) == 2
    assert [e.target_height_mm for e in events] == [1300.0, 450.0]
    assert all(e.bot_id == "214" for e in events)


def test_setforkheight_completion_is_corrected_via_telemetry_not_the_premature_ack():
    # Real gap: actionStatus=FINISHED fires the instant the order is
    # acked, not when the fork physically arrives -- same premature-
    # completion pattern as HTM's simultaneousForkLift, corrected the
    # same way.
    first = build_lift_events(_load())[0]
    assert first.logged_complete_at.strftime("%H:%M:%S.%f")[:-3] == "14:34:52.381"
    assert first.correction_method == "telemetry"
    assert first.corrected_complete_at.strftime("%H:%M:%S.%f")[:-3] == "14:34:55.175"
    assert first.understated_by_seconds == pytest.approx(2.794, abs=0.01)


def test_setforkheight_direction_is_down_for_both_real_pre_positions():
    events = build_lift_events(_load())
    assert [e.direction for e in events] == ["down", "down"]


def test_detects_four_real_tote_transfers_with_pick_drop_labels():
    events = build_tote_transfer_events(_load())
    assert len(events) == 4
    assert [e.label for e in events] == ["pick", "drop", "pick", "drop"]
    assert [e.to_height_mm for e in events] == [1300.0, 850.0, 450.0, 1300.0]


def test_tote_transfer_completion_uses_the_real_actionstates_finished_time():
    # Confirmed real: unlike setForkHeight, tote_unload's own FINISHED
    # genuinely waits for the physical action (telemetry crosses close to
    # the order's own 850mm target right around this same instant) -- no
    # correction needed, used directly as ground truth.
    events = build_tote_transfer_events(_load())
    drop = events[1]
    assert drop.started_at.strftime("%H:%M:%S.%f")[:-3] == "14:35:14.181"  # the tote_unload order
    assert drop.timestamp.strftime("%H:%M:%S.%f")[:-3] == "14:35:25.735"  # actionStatus=FINISHED


def test_combined_fork_adjustment_events_are_the_four_tote_transfers_only():
    # The setForkHeight pre-positions are already fully captured as
    # LiftEvents (with real timing correction) -- they must not ALSO
    # reappear as generic plateau-derived fork_adjustment_events.
    parsed = _load()
    lift_events = build_lift_events(parsed)
    events = build_fork_adjustment_events(parsed, lift_events)
    assert len(events) == 4
    assert [e.label for e in events] == ["pick", "drop", "pick", "drop"]


def test_no_vtm_events_on_lines_with_no_vtm_orders():
    assert build_lift_events([]) == []
    assert build_tote_transfer_events([]) == []
