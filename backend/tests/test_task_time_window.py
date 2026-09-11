"""Unit tests for api/routes.py's _task_time_window -- the tight-vs-loose
pad selection that fixes real cross-task event misattribution (see
routes.py's docstring: task 70f0fa18's lift/rotation events pulled in 2
events each from a different, adjacent task on the same bot under the old
single 120s pad).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.api.routes import _TIGHT_WINDOW_PAD_SECONDS, _BOT_EVENT_WINDOW_PAD_SECONDS, _task_time_window


class FakeEvent:
    def __init__(self, timestamp):
        self.timestamp = timestamp


class FakeTrace:
    def __init__(self, created_at=None, dispatched_at=None, completed_at=None, events=()):
        self.created_at = created_at
        self.dispatched_at = dispatched_at
        self.completed_at = completed_at
        self.events = list(events)


def test_uses_tight_pad_when_created_and_completed_both_known():
    created = datetime(2026, 7, 28, 14, 32, 39, 671000)
    completed = datetime(2026, 7, 28, 14, 34, 40, 524000)
    trace = FakeTrace(created_at=created, completed_at=completed)

    window = _task_time_window(trace)

    assert window == (
        created - timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS),
        completed + timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS),
    )


def test_uses_earliest_event_as_start_when_created_at_missing_but_completed_at_known():
    # Real case: task 70f0fa18 completed cleanly (per its own completion
    # marker) but never logged "#Task created", so created_at is None --
    # the earliest observed event is a tighter, still-correct stand-in.
    first_event_ts = datetime(2026, 7, 28, 14, 32, 44, 975000)
    completed = datetime(2026, 7, 28, 14, 34, 40, 524000)
    trace = FakeTrace(created_at=None, completed_at=completed, events=[FakeEvent(first_event_ts)])

    window = _task_time_window(trace)

    assert window == (
        first_event_ts - timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS),
        completed + timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS),
    )


def test_falls_back_to_loose_pad_when_completed_at_unknown():
    ev = FakeEvent(datetime(2026, 7, 28, 14, 32, 45))
    trace = FakeTrace(created_at=datetime(2026, 7, 28, 14, 32, 39), completed_at=None, events=[ev])

    window = _task_time_window(trace)

    assert window is not None
    start, end = window
    assert (datetime(2026, 7, 28, 14, 32, 39) - start).total_seconds() == _BOT_EVENT_WINDOW_PAD_SECONDS


def test_none_when_no_timestamps_at_all():
    trace = FakeTrace()
    assert _task_time_window(trace) is None
