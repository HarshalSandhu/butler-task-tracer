"""Unit tests for parsers/aggregate_stats.py's cross-task averaging, using
real per-event numbers already established elsewhere this session (task
70f0fa18's two real 250mm-target lift corrections: 3.145s and 3.479s;
task ef3d2ee1's real rotation durations) so the grouping/averaging math is
checked against genuine values, not made-up ones.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import LiftEvent, RotationEvent
from app.parsers.aggregate_stats import TaskWindow, compute_lift_rotation_aggregates


def _lift(order_sent_at, corrected_complete_at, target_mm):
    return LiftEvent(
        bot_id="210",
        order_sent_at=order_sent_at,
        logged_complete_at=order_sent_at,
        target_height_mm=target_mm,
        corrected_complete_at=corrected_complete_at,
        correction_method="telemetry",
        buffer_ms=None,
    )


def _rotation(timestamp, duration_ms):
    return RotationEvent(bot_id="210", timestamp=timestamp, coordinate=None, duration_ms=duration_ms)


def test_groups_lift_durations_by_target_height_and_averages():
    # Real durations from task 70f0fa18 (both target 250mm): 3.145s, 3.479s.
    t0 = datetime(2026, 7, 28, 14, 0, 0)
    task_windows = [
        TaskWindow(task_id="a", bot_id="210", start=t0, end=t0 + timedelta(minutes=5)),
    ]
    lift_events_by_bot = {
        "210": [
            _lift(t0 + timedelta(seconds=10), t0 + timedelta(seconds=13, milliseconds=145), 250.0),
            _lift(t0 + timedelta(seconds=60), t0 + timedelta(seconds=63, milliseconds=479), 250.0),
        ]
    }
    result = compute_lift_rotation_aggregates(task_windows, lift_events_by_bot, {})
    assert result["lift_by_target_height_mm"]["250"]["sample_count"] == 2
    assert result["lift_by_target_height_mm"]["250"]["avg_seconds"] == round((3.145 + 3.479) / 2, 3)


def test_different_target_heights_are_not_blended_together():
    t0 = datetime(2026, 7, 28, 14, 0, 0)
    task_windows = [TaskWindow(task_id="a", bot_id="210", start=t0, end=t0 + timedelta(minutes=5))]
    lift_events_by_bot = {
        "210": [
            _lift(t0, t0 + timedelta(seconds=3), 250.0),
            _lift(t0 + timedelta(seconds=30), t0 + timedelta(seconds=40), 400.0),
        ]
    }
    result = compute_lift_rotation_aggregates(task_windows, lift_events_by_bot, {})
    assert set(result["lift_by_target_height_mm"].keys()) == {"250", "400"}
    assert result["lift_by_target_height_mm"]["250"]["sample_count"] == 1
    assert result["lift_by_target_height_mm"]["400"]["sample_count"] == 1


def test_lift_events_outside_the_task_window_are_excluded():
    # A lift on the same bot but from a DIFFERENT (adjacent) task must not
    # leak into this task's average.
    t0 = datetime(2026, 7, 28, 14, 0, 0)
    task_windows = [TaskWindow(task_id="a", bot_id="210", start=t0, end=t0 + timedelta(minutes=2))]
    lift_events_by_bot = {
        "210": [
            _lift(t0 + timedelta(seconds=10), t0 + timedelta(seconds=13), 250.0),  # in window
            _lift(t0 + timedelta(hours=1), t0 + timedelta(hours=1, seconds=3), 250.0),  # far outside
        ]
    }
    result = compute_lift_rotation_aggregates(task_windows, lift_events_by_bot, {})
    assert result["lift_by_target_height_mm"]["250"]["sample_count"] == 1


def test_averages_rotation_duration_across_tasks():
    t0 = datetime(2026, 7, 28, 14, 0, 0)
    task_windows = [
        TaskWindow(task_id="a", bot_id="210", start=t0, end=t0 + timedelta(minutes=5)),
        TaskWindow(task_id="b", bot_id="214", start=t0, end=t0 + timedelta(minutes=5)),
    ]
    rotation_events_by_bot = {
        "210": [_rotation(t0 + timedelta(seconds=10), 1941.0), _rotation(t0 + timedelta(seconds=20), 2294.0)],
        "214": [_rotation(t0 + timedelta(seconds=15), 2100.0)],
    }
    result = compute_lift_rotation_aggregates(task_windows, {}, rotation_events_by_bot)
    assert result["rotation"]["sample_count"] == 3
    assert result["rotation"]["avg_seconds"] == round((1.941 + 2.294 + 2.1) / 3, 3)


def test_no_data_produces_none_rotation_and_empty_lift_dict():
    task_windows = [TaskWindow(task_id="a", bot_id="210", start=datetime(2026, 7, 28), end=datetime(2026, 7, 29))]
    result = compute_lift_rotation_aggregates(task_windows, {}, {})
    assert result["rotation"] is None
    assert result["lift_by_target_height_mm"] == {}
    assert result["tasks_with_lift_data"] == 0
    assert result["tasks_with_rotation_data"] == 0


def test_task_count_reflects_all_windows_regardless_of_data():
    task_windows = [
        TaskWindow(task_id="a", bot_id="210", start=datetime(2026, 7, 28), end=datetime(2026, 7, 29)),
        TaskWindow(task_id="b", bot_id="214", start=datetime(2026, 7, 28), end=datetime(2026, 7, 29)),
    ]
    result = compute_lift_rotation_aggregates(task_windows, {}, {})
    assert result["task_count"] == 2
