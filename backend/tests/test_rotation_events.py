"""Unit tests for parsers/rotation_events.py against a real navigator_agent
pathlist line (see fixtures/rotation_events_bot200.log) -- the tuple field
decode this module relies on (StepEndMs - StepStartMs = step duration) was
confirmed by manually cross-checking that consecutive entries chain into
one continuous timeline (entry N's start == entry N-1's end) against real
SSH output; this fixture is that same real line.
"""

from __future__ import annotations

import pathlib

from app.parsers.line_parser import parse_lines
from app.parsers.rotation_events import build_rotation_events

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "rotation_events_bot200.log"


def _load():
    lines = FIXTURE_PATH.read_text().splitlines()
    return list(parse_lines(lines))


def test_extracts_only_turn_step_entries_with_correct_durations():
    events = build_rotation_events(_load())
    assert len(events) == 2
    assert [round(e.duration_ms) for e in events] == [1941, 2225]


def test_ignores_non_turn_step_entries():
    events = build_rotation_events(_load())
    coords = [e.coordinate for e in events]
    # acceleration/top_speed/deceleration steps at {24,40}/{24,36}/etc must
    # not leak in as rotation events.
    assert (24, 40) not in coords
    assert (24, 36) not in coords


def test_events_carry_bot_id_and_heuristic_confidence():
    events = build_rotation_events(_load())
    assert all(e.bot_id == "200" for e in events)
    assert all(e.confidence.value == "heuristic" for e in events)


def test_ignores_lines_from_unrelated_functions():
    parsed = _load()
    for p in parsed:
        p.function = "some_other_function"
    assert build_rotation_events(parsed) == []


def test_duplicate_pathlist_snapshot_dedups_by_slot_keeping_latest():
    # Simulates a re-plan re-logging the same upcoming turn (same coord +
    # step index) with a revised end-time -- must keep only the later
    # occurrence's duration, not double-count or keep the stale one.
    raw = FIXTURE_PATH.read_text().strip()
    parsed_first = list(parse_lines([raw]))
    later_line = raw.replace("2026-07-28 04:00:50.819", "2026-07-28 04:00:52.000").replace(
        "687067,689008,", "687067,689500,", 1
    )
    events = build_rotation_events(parsed_first + list(parse_lines([later_line])))
    assert len(events) == 2  # not 4 -- same two (coord, idx) slots, deduped
    first_coord_event = next(e for e in events if e.coordinate == (24, 44))
    assert round(first_coord_event.duration_ms) == 2433  # 689500 - 687067, the LATER value
