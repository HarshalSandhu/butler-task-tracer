"""Second real chargetask trace (165500f6-d46e-43f6-8fa6-ee1d7c691a45, VTM
bot 214) -- covers two things the HTM fixture doesn't:

  1. VTM's own parking attr (`ttp_storable_io_point`), not HTM's
     `relay_storable_io_point`/`relay_storable`.
  2. A real anomaly: `charging_complete` fires TWICE, ~2h10m apart, each
     followed by its own charger_reinit + parking-attr arrival. The
     bounded return-leg window in charge_timing.py is what keeps
     parked_at from jumping across that gap to the second, unrelated
     cycle -- confirmed here against the real timestamps.
"""

from __future__ import annotations

import pathlib

import pytest

from app.parsers.charge_timing import build_charge_timing
from app.parsers.line_parser import parse_lines

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "chargetask_165500f6_vtm.log"


@pytest.fixture
def timing():
    lines = FIXTURE_PATH.read_text().splitlines()
    parsed = list(parse_lines(lines))
    return build_charge_timing(parsed)


def test_charging_complete_takes_the_first_occurrence_not_the_one_2h_later(timing):
    assert timing.charging_complete_at.strftime("%H:%M:%S.%f")[:-3] == "07:44:53.614"


def test_return_reached_charger_reinit_is_the_immediate_one_not_2h_later(timing):
    # A second charger_reinit hit exists at 09:47:25 -- must not be picked.
    assert timing.return_reached_charger_reinit_at.strftime("%H:%M:%S.%f")[:-3] == "07:44:57.322"


def test_parked_at_uses_vtm_ttp_storable_io_point_attr_not_null(timing):
    # A second ttp_storable_io_point hit exists at 09:47:34 -- must not be
    # picked; this must also not be None, which is what the pre-fix
    # HTM-only attr set produced for every VTM chargetask.
    assert timing.parked_at is not None
    assert timing.parked_at.strftime("%H:%M:%S.%f")[:-3] == "07:45:07.188"


def test_return_travel_seconds_is_sane_not_hours(timing):
    # Pre-fix this came out to ~7500s (2h+) by pairing the first
    # charging_complete with the second cycle's parking arrival.
    assert timing.return_travel_seconds < 60


def test_charging_duration_is_real_not_the_2h_gap(timing):
    assert timing.charging_duration_seconds == pytest.approx(480.342, abs=0.01)
