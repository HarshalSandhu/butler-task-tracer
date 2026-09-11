"""Ground-truth regression test for simultaneousForkLift completion-timing
reconstruction, against a real 2-minute capture (bot 209) containing both
correction paths this module supports.
"""

from __future__ import annotations

import pathlib

import pytest

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import build_lift_events, classify_direction

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "lift_events_bot209.log"


@pytest.fixture
def events():
    lines = FIXTURE_PATH.read_text().splitlines(keepends=True)
    parsed = list(parse_lines(lines))
    return build_lift_events(parsed)


def test_finds_both_lift_events_in_the_window(events):
    assert len(events) == 2
    assert all(e.bot_id == "209" for e in events)


def test_first_event_is_a_maxdown_noop_with_no_correction(events):
    """Fork was already at 262mm (within 10mm of the 260mm target) *before*
    the order was even sent, AND this is an explicit maxdown-settle order
    (see _MAXDOWN_SETTLE_COMPLETE_RE) -- the fork never actually moved, so
    no correction should be applied at all. Confirmed real (task
    fc94362b-4546-427d-ac1d-291706f2fb93, bot 208): applying the
    estimated_buffer travel-time estimate here previously invented a
    spurious ~5-8s "overlap" for a lift that was a no-op the entire time --
    a stale/delayed telemetry sample confirming a height the bot was
    already at, not a real physical settling delay."""
    ev = events[0]
    assert ev.target_height_mm == 260.0
    assert ev.correction_method is None
    assert ev.buffer_ms is None
    assert ev.understated_by_seconds is None
    assert ev.corrected_complete_at is None


def test_second_event_uses_real_telemetry_crossing(events):
    """Fork genuinely descends 878mm -> 472mm -> 298mm -> 262mm here -- this
    must use the real ground-truth crossing, not the buffer estimate, and
    the ground-truth answer is provably *earlier* than the buffer estimate
    would have said (a real reason telemetry has to be tried first)."""
    ev = events[1]
    assert ev.target_height_mm == 260.0
    assert ev.correction_method == "telemetry"
    assert ev.corrected_complete_at.strftime("%H:%M:%S.%f")[:-3] == "14:43:22.075"
    assert ev.corrected_complete_at > ev.logged_complete_at
    # the buffer estimate for this same event would have overshot the real answer
    buffer_estimate = ev.logged_complete_at.timestamp() + ev.buffer_ms / 1000.0
    assert ev.corrected_complete_at.timestamp() < buffer_estimate


def test_order_correlated_to_correct_target_height(events):
    assert events[0].order_sent_at.strftime("%H:%M:%S.%f")[:-3] == "14:42:45.700"
    assert events[1].order_sent_at.strftime("%H:%M:%S.%f")[:-3] == "14:43:17.368"


def test_direction_none_when_fork_already_near_target(events):
    # event[0]: fork already at 262mm, target 260mm -- a same-height
    # confirmation, not a real move.
    assert events[0].direction is None


def test_direction_down_when_fork_genuinely_descends(events):
    # event[1]: fork descends 878mm -> ... -> 262mm against a 260mm target.
    assert events[1].direction == "down"


def test_classify_direction_thresholds():
    assert classify_direction(pre_height_mm=478.0, target_mm=250.0) == "down"
    assert classify_direction(pre_height_mm=100.0, target_mm=250.0) == "up"
    assert classify_direction(pre_height_mm=252.0, target_mm=250.0) is None  # within tolerance
    assert classify_direction(pre_height_mm=None, target_mm=250.0) is None
    assert classify_direction(pre_height_mm=252.0, target_mm=None) is None
