"""Battery-level-at-milestone tracking (charge_timing.py's
attach_battery_levels) and the docked_to_charging_started_seconds property
-- against a real chargetask trace (87e760ef-1639-4b02-9c06-7efcefc8148d,
bot 210) confirmed via direct SSH: 57.0% right at reached_charger_at,
70.0% right at charging_complete_at, a real ~10-minute, 13-point rise.
"""

from __future__ import annotations

import pathlib

import pytest

from app.parsers.charge_timing import attach_battery_levels, build_charge_timing
from app.parsers.lift_events import parse_battery_telemetry
from app.parsers.line_parser import parse_lines

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
TASK_LINES = (FIXTURES / "chargetask_87e760ef.log").read_text().splitlines()
BATTERY_LINES = (FIXTURES / "chargetask_87e760ef_battery.log").read_text().splitlines()
BOT_ID = "210"


@pytest.fixture
def timing():
    t = build_charge_timing(list(parse_lines(TASK_LINES)))
    battery_telemetry = parse_battery_telemetry(list(parse_lines(BATTERY_LINES)))
    attach_battery_levels(t, battery_telemetry.get(BOT_ID, []))
    return t


def test_battery_pct_at_charger_arrival(timing):
    assert timing.battery_pct_at_charger_arrival == 57.0


def test_battery_pct_at_charging_complete(timing):
    assert timing.battery_pct_at_charging_complete == 70.0


def test_docked_to_charging_started_is_near_instant_in_this_real_trace(timing):
    # Confirmed real: reached_charger_at and charging_started_at landed
    # only 16ms apart in this trace -- charging began essentially the
    # instant the bot docked, not after a separate waiting period.
    assert timing.docked_to_charging_started_seconds == pytest.approx(0.016, abs=0.001)


def test_charging_duration_and_return_leg_are_distinct_numbers(timing):
    # The bifurcation the user asked to see clearly: how long actual
    # charging took vs. how long it took to back out to charger_reinit
    # afterward -- two very different, already-separate numbers.
    assert timing.charging_duration_seconds == pytest.approx(602.696, abs=0.01)
    assert timing.charging_stop_to_reinit_seconds == pytest.approx(4.261, abs=0.01)


def test_attach_battery_levels_leaves_fields_none_without_readings():
    t = build_charge_timing(list(parse_lines(TASK_LINES)))
    attach_battery_levels(t, [])
    assert t.battery_pct_at_charger_arrival is None
    assert t.battery_pct_at_charging_complete is None


def test_docked_to_charging_started_is_none_without_both_timestamps():
    from app.models import ChargeTiming

    assert ChargeTiming().docked_to_charging_started_seconds is None


def test_graceful_stop_api_stop_detected(timing):
    # Confirmed real: this trace's charging_complete was actually triggered
    # by an API-issued graceful stop (graceful_stop_reason=api_stop), not
    # the bot reaching full charge -- the ack (12:14:38.978) lands ~9.17s
    # before charging_complete fires (12:14:48.144).
    assert timing.graceful_stop_reason == "api_stop"
    assert timing.graceful_stop_at is not None
    assert timing.charging_stopped_via_api is True


def test_charging_stopped_via_api_false_without_graceful_stop_line():
    from app.models import ChargeTiming

    assert ChargeTiming().charging_stopped_via_api is False


def test_charging_stopped_via_api_false_when_gap_exceeds_tolerance():
    from datetime import datetime, timedelta

    from app.models import ChargeTiming

    t = ChargeTiming()
    t.charging_complete_at = datetime(2026, 8, 3, 12, 0, 0)
    t.graceful_stop_at = t.charging_complete_at - timedelta(seconds=60)
    t.graceful_stop_reason = "api_stop"
    assert t.charging_stopped_via_api is False
