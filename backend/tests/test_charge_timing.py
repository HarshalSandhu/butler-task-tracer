"""Ground-truth regression test: a real chargetask trace
(001d1a82-f75f-4c1d-9568-2dd5ba33ecfb, bot 206) captured and manually
verified this session -- see charge_timing.py's module docstring for the
full real timeline this checks against.
"""

from __future__ import annotations

import pathlib

import pytest

from app.parsers.charge_timing import build_charge_timing
from app.parsers.line_parser import parse_lines

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "chargetask_001d1a82.log"


@pytest.fixture
def timing():
    lines = FIXTURE_PATH.read_text().splitlines()
    parsed = list(parse_lines(lines))
    return build_charge_timing(parsed)


def test_assigned_at(timing):
    assert timing.assigned_at.strftime("%H:%M:%S.%f")[:-3] == "11:14:17.496"


def test_reached_charger_reinit_outbound(timing):
    assert timing.reached_charger_reinit_at.strftime("%H:%M:%S.%f")[:-3] == "11:14:48.716"


def test_reached_charger(timing):
    assert timing.reached_charger_at.strftime("%H:%M:%S.%f")[:-3] == "11:15:25.479"


def test_charging_started(timing):
    assert timing.charging_started_at.strftime("%H:%M:%S.%f")[:-3] == "11:15:25.484"


def test_charging_complete(timing):
    assert timing.charging_complete_at.strftime("%H:%M:%S.%f")[:-3] == "11:26:28.347"


def test_return_dispatched(timing):
    assert timing.return_dispatched_at.strftime("%H:%M:%S.%f")[:-3] == "11:27:32.099"


def test_return_reached_charger_reinit(timing):
    assert timing.return_reached_charger_reinit_at.strftime("%H:%M:%S.%f")[:-3] == "11:28:48.519"


def test_parked_at_is_the_final_relay_attr_after_charging_complete(timing):
    # Real trace reaches relay_storable_io_point at 29:07.747, THEN
    # relay_storable at 29:10.518 -- "parked" should be the last one, not
    # the first, since the bot keeps moving until it actually settles.
    assert timing.parked_at.strftime("%H:%M:%S.%f")[:-3] == "11:29:10.518"


def test_outbound_travel_seconds(timing):
    assert timing.outbound_travel_seconds == pytest.approx(67.983, abs=0.01)


def test_charging_duration_seconds(timing):
    assert timing.charging_duration_seconds == pytest.approx(662.863, abs=0.01)


def test_return_travel_seconds(timing):
    assert timing.return_travel_seconds == pytest.approx(162.171, abs=0.01)


def test_total_seconds(timing):
    assert timing.total_seconds == pytest.approx(893.022, abs=0.01)


def test_assigned_to_reinit_seconds(timing):
    assert timing.assigned_to_reinit_seconds == pytest.approx(31.220, abs=0.01)


def test_reinit_to_charger_seconds(timing):
    assert timing.reinit_to_charger_seconds == pytest.approx(36.763, abs=0.01)


def test_charging_stop_to_reinit_seconds(timing):
    assert timing.charging_stop_to_reinit_seconds == pytest.approx(140.172, abs=0.01)


def test_reinit_to_parked_seconds(timing):
    assert timing.reinit_to_parked_seconds == pytest.approx(21.999, abs=0.01)


def test_outbound_sub_legs_sum_to_outbound_travel(timing):
    assert timing.assigned_to_reinit_seconds + timing.reinit_to_charger_seconds == pytest.approx(
        timing.outbound_travel_seconds, abs=0.01
    )


def test_return_sub_legs_sum_to_return_travel(timing):
    assert timing.charging_stop_to_reinit_seconds + timing.reinit_to_parked_seconds == pytest.approx(
        timing.return_travel_seconds, abs=0.01
    )


def test_empty_input_produces_all_none():
    timing = build_charge_timing([])
    assert timing.assigned_at is None
    assert timing.outbound_travel_seconds is None
    assert timing.charging_duration_seconds is None
    assert timing.return_travel_seconds is None
    assert timing.total_seconds is None
