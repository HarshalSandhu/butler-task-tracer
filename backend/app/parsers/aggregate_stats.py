"""24h aggregate lift/rotation stats for relay_pps_task -- answers "on
average, how long does a simultaneous lift take for a given target fork
height, and how long does rotation take overall" across every
relay_pps_task in a scan window, not just one task at a time.

Deliberately keyed by TARGET FORK HEIGHT (not by task) for the lift
average: a `simultaneousForkLift` order's real (corrected) duration is
primarily a function of how far the fork has to travel, and this session's
single-task captures confirmed the same target height (e.g. 250mm, the
"maxdown" height) recurs across every relay_pps_task instance -- so
grouping by it is what makes "average" a meaningful number instead of
blending physically different moves together.

`corrected_complete_at - order_sent_at` is the duration averaged, not the
naively-logged (premature) one -- see lift_events.py's module docstring for
why the logged timestamp alone understates real completion time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import LiftEvent, RotationEvent


@dataclass
class TaskWindow:
    task_id: str
    bot_id: str
    start: datetime
    end: datetime


def compute_lift_rotation_aggregates(
    task_windows: list[TaskWindow],
    lift_events_by_bot: dict[str, list[LiftEvent]],
    rotation_events_by_bot: dict[str, list[RotationEvent]],
) -> dict:
    """`lift_events_by_bot`/`rotation_events_by_bot` should already cover
    (at least) each task_window's own [start, end] span for that bot --
    this function only slices and aggregates, it doesn't fetch anything.
    """
    lift_durations_by_height: dict[int, list[float]] = {}
    rotation_durations: list[float] = []
    tasks_with_lift_data = 0
    tasks_with_rotation_data = 0

    for tw in task_windows:
        task_lifts = [
            le
            for le in lift_events_by_bot.get(tw.bot_id, [])
            if le.order_sent_at is not None
            and tw.start <= le.order_sent_at <= tw.end
            and le.corrected_complete_at is not None
            and le.target_height_mm is not None
        ]
        if task_lifts:
            tasks_with_lift_data += 1
        for le in task_lifts:
            duration = (le.corrected_complete_at - le.order_sent_at).total_seconds()
            lift_durations_by_height.setdefault(round(le.target_height_mm), []).append(duration)

        task_rotations = [
            re_ for re_ in rotation_events_by_bot.get(tw.bot_id, []) if tw.start <= re_.timestamp <= tw.end
        ]
        if task_rotations:
            tasks_with_rotation_data += 1
        rotation_durations.extend(re_.duration_ms / 1000.0 for re_ in task_rotations)

    lift_by_height = {
        str(height_mm): {
            "avg_seconds": round(sum(durations) / len(durations), 3),
            "sample_count": len(durations),
        }
        for height_mm, durations in sorted(lift_durations_by_height.items())
    }

    rotation_summary = (
        {
            "avg_seconds": round(sum(rotation_durations) / len(rotation_durations), 3),
            "sample_count": len(rotation_durations),
        }
        if rotation_durations
        else None
    )

    return {
        "task_count": len(task_windows),
        "tasks_with_lift_data": tasks_with_lift_data,
        "tasks_with_rotation_data": tasks_with_rotation_data,
        "lift_by_target_height_mm": lift_by_height,
        "rotation": rotation_summary,
    }
