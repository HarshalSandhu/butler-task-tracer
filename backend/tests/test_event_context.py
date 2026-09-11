"""Unit tests for parsers/event_context.py, using the real phase timestamps
recovered from task 70f0fa18-c9d9-4992-b209-0225654bf05f (see the raw log
pulled from the validation VM) to ground the "major" rotation window and
the lift context labels in an actual trace, not synthetic guesses.
"""

from __future__ import annotations

from datetime import datetime

from app.models import Confidence, ForkAdjustmentEvent, LiftEvent, RotationEvent
from app.parsers.event_context import (
    annotate_event_context,
    classify_rotation_significance,
    label_fork_adjustment,
    label_lift_context,
    label_rotation_context,
    nearest_phase_attr,
)

# Real phase_durations()-shaped data for task 70f0fa18 (from its actual trace).
PHASES = [
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 28, 14, 32, 55, 561000)},
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable",
     "timestamp": datetime(2026, 7, 28, 14, 32, 59, 723000)},
    {"from_attr": "relay_storable", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 28, 14, 33, 7, 324000)},
    {"from_attr": "relay_storable_io_point", "to_attr": "pps_entry_queue",
     "timestamp": datetime(2026, 7, 28, 14, 33, 49, 167000)},
    {"from_attr": "pps_entry_queue", "to_attr": "pps",
     "timestamp": datetime(2026, 7, 28, 14, 33, 51, 976000)},
    {"from_attr": "pps", "to_attr": "highway",
     "timestamp": datetime(2026, 7, 28, 14, 34, 1, 764000)},
    {"from_attr": "highway", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 28, 14, 34, 26, 711000)},
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable",
     "timestamp": datetime(2026, 7, 28, 14, 34, 30, 459000)},
    {"from_attr": "relay_storable", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 28, 14, 34, 37, 937000)},
]


def _lift(order_sent_at, direction=None):
    return LiftEvent(
        bot_id="210",
        order_sent_at=order_sent_at,
        logged_complete_at=order_sent_at,
        target_height_mm=250.0,
        corrected_complete_at=None,
        correction_method=None,
        buffer_ms=None,
        direction=direction,
    )


def _rotation(timestamp):
    return RotationEvent(bot_id="210", timestamp=timestamp, coordinate=(14, 36), duration_ms=1941.0)


def _fork(timestamp, direction, from_h=252.0, to_h=478.0):
    return ForkAdjustmentEvent(
        bot_id="210", timestamp=timestamp, from_height_mm=from_h, to_height_mm=to_h, direction=direction
    )


def test_nearest_phase_attr_picks_closest_arrival():
    ts = datetime(2026, 7, 28, 14, 33, 7, 500000)  # just after the 07.324 arrival
    attr, delta = nearest_phase_attr(ts, PHASES)
    assert attr == "relay_storable_io_point"
    assert round(delta, 3) == 0.176


def test_label_lift_context_after_pickup_is_lift_down_at_relay_storable_io_point():
    # Real event: order sent 14:33:07.330, right at the relay_storable_io_point
    # arrival that follows the pickup at relay_storable.
    lift = _lift(datetime(2026, 7, 28, 14, 33, 7, 330000), direction="down")
    label = label_lift_context(lift, PHASES)
    assert label == "lift down @ relay_storable_io_point"


def test_label_lift_context_falls_back_when_no_phases():
    lift = _lift(datetime(2026, 7, 28, 14, 33, 7, 330000), direction="down")
    assert label_lift_context(lift, []) is None


def test_label_lift_context_with_no_direction_still_labels_location():
    lift = _lift(datetime(2026, 7, 28, 14, 32, 44, 982000), direction=None)
    assert label_lift_context(lift, PHASES) == "lift @ relay_storable_io_point"


def test_rotation_near_relay_storable_io_point_arrival_is_major():
    # Real rotation at 14:32:45.627, ~0.65s after the {14,49} arrival that
    # feeds into the first relay_storable_io_point phase.
    rot = _rotation(datetime(2026, 7, 28, 14, 32, 45, 627000))
    assert classify_rotation_significance(rot, PHASES) == "major"


def test_rotation_mid_highway_travel_is_minor():
    # Nowhere near any waypoint arrival -- deep in the 41.8s highway leg.
    rot = _rotation(datetime(2026, 7, 28, 14, 33, 25, 0))
    assert classify_rotation_significance(rot, PHASES) == "minor"


def test_fork_adjustment_at_relay_storable_is_pick_when_rising():
    # Real event: 14:33:01.976, rising 252->478mm, right at the
    # relay_storable arrival (59.723) -- the actual tote pickup.
    fork = _fork(datetime(2026, 7, 28, 14, 33, 1, 976000), direction="up")
    assert label_fork_adjustment(fork, PHASES) == "pick"


def test_fork_adjustment_at_relay_storable_is_drop_when_falling():
    fork = _fork(datetime(2026, 7, 28, 14, 32, 59, 800000), direction="down")
    assert label_fork_adjustment(fork, PHASES) == "drop"


def test_fork_adjustment_elsewhere_uses_generic_lift_label():
    # Real event: 14:34:26.519, rising 252->478mm, right at the
    # highway -> relay_storable_io_point arrival (26.711) -- not the
    # storable slot itself, so no "pick" label here.
    fork = _fork(datetime(2026, 7, 28, 14, 34, 26, 519000), direction="up")
    assert label_fork_adjustment(fork, PHASES) == "lift up @ relay_storable_io_point"


def test_fork_adjustment_falls_back_when_no_phases():
    fork = _fork(datetime(2026, 7, 28, 14, 33, 1, 976000), direction="up")
    assert label_fork_adjustment(fork, []) == "lift up"


# Real phase_durations()-shaped data for task
# 6227a076-190b-42dc-a957-f5523dbc2f94 (bot 200), WITH duration_seconds --
# used for the departure-aware ("pps exit") rotation labeling tests below,
# which PHASES above can't exercise since it omits duration_seconds.
PHASES_WITH_DURATIONS = [
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 29, 6, 39, 18, 224000), "duration_seconds": 10.298},
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable",
     "timestamp": datetime(2026, 7, 29, 6, 39, 21, 204000), "duration_seconds": 2.98},
    {"from_attr": "relay_storable", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 29, 6, 39, 27, 912000), "duration_seconds": 6.708},
    {"from_attr": "relay_storable_io_point", "to_attr": "pps_entry_queue",
     "timestamp": datetime(2026, 7, 29, 6, 40, 5, 770000), "duration_seconds": 37.858},
    {"from_attr": "pps_entry_queue", "to_attr": "pps",
     "timestamp": datetime(2026, 7, 29, 6, 40, 8, 602000), "duration_seconds": 2.832},
    {"from_attr": "pps", "to_attr": "pps",
     "timestamp": datetime(2026, 7, 29, 6, 41, 2, 442000), "duration_seconds": 53.84},
    {"from_attr": "pps", "to_attr": "highway",
     "timestamp": datetime(2026, 7, 29, 6, 41, 10, 614000), "duration_seconds": 8.172},
    {"from_attr": "highway", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 29, 6, 41, 33, 638000), "duration_seconds": 23.024},
    {"from_attr": "relay_storable_io_point", "to_attr": "relay_storable",
     "timestamp": datetime(2026, 7, 29, 6, 41, 37, 792000), "duration_seconds": 4.154},
    {"from_attr": "relay_storable", "to_attr": "relay_storable_io_point",
     "timestamp": datetime(2026, 7, 29, 6, 41, 44, 589000), "duration_seconds": 6.797},
]


def test_rotation_right_after_leaving_pps_is_labeled_pps_exit():
    # Real rotation at 06:41:07.459 (task 6227a076..., bot 200): lands
    # 1.14s after the "pps -> pps" phase's own departure instant (08.602s
    # earlier, right after the "lift down @ pps" fork descent) but ~5.0s
    # from the nearest ARRIVAL (at "highway", not a key waypoint) -- the
    # arrival-only version of this check used to call this "minor" and
    # silently drop it, hiding the "just came out of pps" rotation entirely.
    rot = _rotation(datetime(2026, 7, 29, 6, 41, 7, 459000))
    assert label_rotation_context(rot, PHASES_WITH_DURATIONS) == "pps exit"
    assert classify_rotation_significance(rot, PHASES_WITH_DURATIONS) == "major"


def test_rotation_at_arrival_still_labeled_by_arrival_not_departure():
    # Real rotation at 06:41:33.619, essentially coincident with the
    # highway -> relay_storable_io_point phase's own arrival (06:41:33.638)
    # -- must still resolve to the arrival wording, not a spurious "exit".
    rot = _rotation(datetime(2026, 7, 29, 6, 41, 33, 619000))
    assert label_rotation_context(rot, PHASES_WITH_DURATIONS) == "arrival @ relay_storable_io_point"
    assert classify_rotation_significance(rot, PHASES_WITH_DURATIONS) == "major"


def test_departure_check_is_skipped_when_phases_lack_duration_seconds():
    # PHASES (above) has no duration_seconds key at all -- must not raise,
    # and must fall back to the pre-existing arrival-only behavior.
    rot = _rotation(datetime(2026, 7, 28, 14, 32, 45, 627000))
    assert label_rotation_context(rot, PHASES) == "arrival @ relay_storable_io_point"


def test_annotate_event_context_mutates_trace_in_place():
    class FakeTrace:
        def __init__(self):
            self.lift_events = [_lift(datetime(2026, 7, 28, 14, 33, 7, 330000), direction="down")]
            self.rotation_events = [_rotation(datetime(2026, 7, 28, 14, 32, 45, 627000))]
            self.fork_adjustment_events = [_fork(datetime(2026, 7, 28, 14, 33, 1, 976000), direction="up")]

        def phase_durations(self):
            return PHASES

    trace = FakeTrace()
    annotate_event_context(trace)
    assert trace.lift_events[0].context_label == "lift down @ relay_storable_io_point"
    assert trace.rotation_events[0].significance == "major"
    assert trace.fork_adjustment_events[0].label == "pick"
