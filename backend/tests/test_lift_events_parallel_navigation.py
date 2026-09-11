"""Regression test for the second, differently-worded simultaneousForkLift
premature-completion message -- "Fork height adjustment completed during
parallel navigation" (issued via compute_parallel_lift_goto_barcode, a
lift that happens while the bot is already traveling), as opposed to the
originally-handled "...completed for simultaneous_fork_lift_to_maxdown_
height subtask" wording.

Confirmed real gap (task da1cfdc4-5f0d-49c5-8678-157d9f4675a3, bot 209):
a genuine `Order = {simultaneousForkLift, #{..., fork_height => 880, ...}}`
at 11:45:25.858 with its completion notice worded the second way was
previously invisible to _PREMATURE_COMPLETE_RE entirely (and to the SSH
marker pattern, which filtered the raw line out before it even reached
this parser) -- it fell through to the generic telemetry-plateau fallback
instead, with no order/timing-correction pairing at all.
"""

from __future__ import annotations

import pathlib

from app.parsers.line_parser import parse_lines
from app.parsers.lift_events import build_lift_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "lift_events_da1cfdc4_parallel_nav.log"


def _load():
    return list(parse_lines(FIXTURE_PATH.read_text().splitlines()))


def test_detects_the_parallel_navigation_lift():
    events = build_lift_events(_load())
    matches = [e for e in events if e.target_height_mm == 880.0]
    assert len(matches) == 1
    lift = matches[0]
    assert lift.order_sent_at.strftime("%H:%M:%S.%f")[:-3] == "11:45:25.858"
    assert lift.logged_complete_at.strftime("%H:%M:%S.%f")[:-3] == "11:45:29.564"


def test_parallel_navigation_completion_is_corrected_via_telemetry():
    events = build_lift_events(_load())
    lift = next(e for e in events if e.target_height_mm == 880.0)
    assert lift.correction_method == "telemetry"
    assert lift.corrected_complete_at.strftime("%H:%M:%S.%f")[:-3] == "11:45:34.014"
    assert lift.understated_by_seconds > 0


def test_maxdown_wording_still_works_alongside_the_new_pattern():
    # Both completion-message variants must coexist correctly in the same
    # fixture -- this file has real examples of each.
    events = build_lift_events(_load())
    maxdown_like = [e for e in events if e.target_height_mm == 260.0]
    assert len(maxdown_like) >= 3
