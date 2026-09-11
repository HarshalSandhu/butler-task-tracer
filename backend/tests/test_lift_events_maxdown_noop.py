"""Regression tests for the maxdown-settle no-op suppression in
build_lift_events -- an EXPLICIT `simultaneous_fork_lift_to_maxdown_height`
order whose target is already within 10mm of the fork's pre-order height
never really moved, so no telemetry/buffer correction should be invented
for it (see lift_events.py's is_maxdown_noop).

Confirmed real (task fc94362b-4546-427d-ac1d-291706f2fb93, bot 208): before
this fix, this exact case produced a spurious ~7.9s "estimated_buffer"
overlap for a lift that was a no-op the entire time.

Deliberately does NOT apply to a "during parallel navigation" completion
(a real functional lift mid-travel, never a settle) even when its target
coincidentally lands within 10mm of the pre-order height -- tested here
with constructed lines since a real coincidental-proximity capture of that
specific combination hasn't been observed in the wild.
"""

from __future__ import annotations

import pathlib

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import _MAXDOWN_SETTLE_COMPLETE_RE, build_lift_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "lift_events_fc94362b_maxdown_noop.log"


def _load(path: pathlib.Path):
    return list(parse_lines(path.read_text().splitlines()))


def test_maxdown_settle_wording_matches_only_the_explicit_subtask():
    maxdown_line = (
        "2026-08-19 04:43:32.686 [info][<0.1.0>] --- rm_messages:handle:{257,14}: "
        "butler_id=208 Fork height adjustment completed for simultaneous_fork_lift_to_maxdown_height subtask"
    )
    parallel_nav_line = (
        "2026-08-19 04:43:33.069 [info][<0.1.0>] --- rm_messages:handle:{264,14}: "
        "butler_id=208 Fork height adjustment completed during parallel navigation"
    )
    assert _MAXDOWN_SETTLE_COMPLETE_RE.search(maxdown_line) is not None
    assert _MAXDOWN_SETTLE_COMPLETE_RE.search(parallel_nav_line) is None


def test_real_maxdown_noop_gets_no_correction():
    events = build_lift_events(_load(FIXTURE_PATH))
    noop = next(e for e in events if e.target_height_mm == 260.0)
    assert noop.correction_method is None
    assert noop.corrected_complete_at is None
    assert noop.buffer_ms is None
    assert noop.understated_by_seconds is None
    # Still a real event -- kept, just without a fabricated correction.
    assert noop.logged_complete_at is not None
    assert noop.direction is None


def _synthetic_lines(*message_lines: str) -> list:
    return list(parse_lines(message_lines))


def test_explicit_maxdown_away_from_target_is_still_corrected():
    # Genuine down-move to maxdown (550mm -> 260mm, well outside the 10mm
    # tolerance) -- correction must still apply normally, confirming the
    # suppression is height-gated, not a blanket disable for every maxdown
    # order.
    lines = _synthetic_lines(
        "2026-08-19 05:00:00.000 [debug][<0.1.0>] --- vda5050_v2:handle_msg:{89,6}: "
        'butler_id=300 #recv: Topic = <<"x">>, Payload = #{<<"agvPosition">> => '
        '#{<<"liftHeight">> => 0.550,<<"theta">> => 0.0,<<"x">> => 1.0,<<"y">> => 2.0}}',
        "2026-08-19 05:00:01.000 [debug][<0.1.0>] --- gmc_mqtt_agv_communicator:pub_order:{684,6}: "
        "butler_id=300 #pub: Order = {simultaneousForkLift,#{id => 300,fork_height => 260}}",
        "2026-08-19 05:00:01.300 [info][<0.1.0>] --- rm_messages:handle:{257,14}: "
        "butler_id=300 Fork height adjustment completed for simultaneous_fork_lift_to_maxdown_height subtask",
        "2026-08-19 05:00:01.310 [debug][<0.1.0>] --- vertical_movement_utils:simultaneous_lift_time_for_fork:{390,6}: "
        "butler_id=300 fork travel 550 -> 260 mm (clamped to 260), time=2000.0 ms, finaltime_with_buffer=5000.0 ms",
    )
    events = build_lift_events(lines)
    assert len(events) == 1
    ev = events[0]
    assert ev.target_height_mm == 260.0
    assert ev.correction_method == "estimated_buffer"
    assert ev.corrected_complete_at is not None
    assert ev.direction == "down"


def test_parallel_navigation_near_target_is_not_treated_as_noop():
    # Same coincidental proximity (pre-height 262mm, target 260mm) as the
    # real maxdown-noop case above, but via the "during parallel
    # navigation" wording instead -- must NOT be suppressed, since this is
    # never a maxdown-settle order regardless of its numeric target.
    lines = _synthetic_lines(
        "2026-08-19 05:00:00.000 [debug][<0.1.0>] --- vda5050_v2:handle_msg:{89,6}: "
        'butler_id=301 #recv: Topic = <<"x">>, Payload = #{<<"agvPosition">> => '
        '#{<<"liftHeight">> => 0.262,<<"theta">> => 0.0,<<"x">> => 1.0,<<"y">> => 2.0}}',
        "2026-08-19 05:00:01.000 [debug][<0.1.0>] --- gmc_mqtt_agv_communicator:pub_order:{684,6}: "
        "butler_id=301 #pub: Order = {simultaneousForkLift,#{id => 301,fork_height => 260}}",
        "2026-08-19 05:00:01.300 [info][<0.1.0>] --- rm_messages:handle:{264,14}: "
        "butler_id=301 Fork height adjustment completed during parallel navigation",
        "2026-08-19 05:00:01.310 [debug][<0.1.0>] --- vertical_movement_utils:simultaneous_lift_time_for_fork:{390,6}: "
        "butler_id=301 fork travel 262 -> 260 mm (clamped to 260), time=100.0 ms, finaltime_with_buffer=3000.0 ms",
    )
    events = build_lift_events(lines)
    assert len(events) == 1
    ev = events[0]
    assert ev.target_height_mm == 260.0
    # NOT suppressed -- gets the normal estimated_buffer correction like any
    # other lift, since this was never an explicit maxdown-settle order.
    assert ev.correction_method == "estimated_buffer"
    assert ev.corrected_complete_at is not None
