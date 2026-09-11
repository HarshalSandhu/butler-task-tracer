"""Labels lift/rotation events with the task-specific context that
lift_events.py/rotation_events.py can't see on their own -- both operate on
bare bot-window log lines with no notion of "this task's own movement
phases". This module is the thing that actually knows about `TaskTrace`
phases, so it's where lift events get a human-readable location label and
rotation events get split into "major" (near a key waypoint) vs "minor"
(ordinary in-transit turns).

Deliberately NOT trying to invent domain terminology like "pps entry
lift"/"pps exit lift" -- the label is built directly from the nearest real,
observed `to_attr` off the trace's own phases (e.g. "lift down @
relay_storable"), so it can never claim something the log itself didn't
show.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import ForkAdjustmentEvent, LiftEvent, RotationEvent

# The one waypoint where a fork-adjustment event gets the user's own
# "pick"/"drop" vocabulary instead of the generic "lift up"/"lift down" --
# relay_storable is specifically the tote load/unload slot, unlike
# relay_storable_io_point (just the approach point) or pps (a handoff, not
# a pick/drop against a physical shelf).
PICK_DROP_ATTR = "relay_storable"

# The waypoints where "the bot reaches the io point, then rotates" actually
# applies -- relay_storable_io_point (VTM/HTM handoff point) and the two
# pps-side attrs observed for relay_pps_task (pps_entry_queue, pps itself).
KEY_WAYPOINT_ATTRS = frozenset({"relay_storable_io_point", "pps_entry_queue", "pps"})

# How close (in time) a rotation needs to land to a waypoint arrival to
# count as "because of" that arrival, rather than an unrelated in-transit
# turn. Rotations in the real capture used to validate this landed within
# ~1s of the matching phase's arrival instant; 10s leaves comfortable
# margin without pulling in a *different* waypoint's rotation.
MAJOR_ROTATION_WINDOW_SECONDS = 10.0


def nearest_phase_attr(timestamp: datetime, phases: list[dict]) -> tuple[str | None, float | None]:
    """(to_attr, seconds_away) of whichever phase's arrival instant
    (`phase["timestamp"]`) is closest to `timestamp`. (None, None) if there
    are no phases at all."""
    best_attr: str | None = None
    best_delta: float | None = None
    for p in phases:
        delta = abs((timestamp - p["timestamp"]).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_attr = p["to_attr"]
    return best_attr, best_delta


def _nearest_key_departure_attr(timestamp: datetime, phases: list[dict]) -> tuple[str | None, float | None]:
    """(from_attr, seconds_away) of whichever phase's *departure* instant
    (`phase["timestamp"] - phase["duration_seconds"]`, i.e. when the
    previous phase ended and this one's travel began) is closest to
    `timestamp`, considering ONLY phases departing a KEY_WAYPOINT_ATTRS
    waypoint -- the mirror of nearest_phase_attr's arrival check, needed
    for "just left pps" the same way arrival covers "just reached pps".

    Restricted to key-attr departures deliberately, not just "nearest
    departure overall" -- confirmed necessary against a real capture (task
    6227a076..., bot 200): for the rotation at 06:41:07.459, the globally
    nearest departure is "highway" at 3.16s (from the *following* phase,
    highway -> relay_storable_io_point), while the real "just left pps"
    departure is 5.02s away -- an unfiltered nearest-departure search picks
    the closer-but-irrelevant "highway" and never finds pps at all.

    Phases missing `duration_seconds` (some callers pass a reduced fixture)
    are skipped rather than raising. (None, None) if no phase qualifies.
    """
    best_attr: str | None = None
    best_delta: float | None = None
    for p in phases:
        duration = p.get("duration_seconds")
        if duration is None or p["from_attr"] not in KEY_WAYPOINT_ATTRS:
            continue
        departure_ts = p["timestamp"] - timedelta(seconds=duration)
        delta = abs((timestamp - departure_ts).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_attr = p["from_attr"]
    return best_attr, best_delta


def label_lift_context(lift_event: LiftEvent, phases: list[dict]) -> str | None:
    if not phases:
        return None
    anchor = lift_event.order_sent_at or lift_event.logged_complete_at
    attr, _ = nearest_phase_attr(anchor, phases)
    direction_word = {"up": "lift up", "down": "lift down"}.get(lift_event.direction, "lift")
    return f"{direction_word} @ {attr}" if attr else direction_word


def label_fork_adjustment(fork_event: ForkAdjustmentEvent, phases: list[dict]) -> str:
    # Ground-truth events (build_tote_transfer_events: htm_load_tote/
    # htm_unload_tote) already carry a real, order-derived "pick"/"drop"
    # label -- never overwrite that with the nearest-waypoint guess below,
    # which exists only for the telemetry-plateau-derived events that have
    # no direct action-type signal of their own.
    if fork_event.label is not None:
        return fork_event.label
    attr, _ = nearest_phase_attr(fork_event.timestamp, phases)
    if attr == PICK_DROP_ATTR:
        return "pick" if fork_event.direction == "up" else "drop"
    direction_word = "lift up" if fork_event.direction == "up" else "lift down"
    return f"{direction_word} @ {attr}" if attr else direction_word


def label_rotation_context(
    rotation_event: RotationEvent,
    phases: list[dict],
    window_seconds: float = MAJOR_ROTATION_WINDOW_SECONDS,
) -> str | None:
    """"pps exit"-style label when this rotation lands near a key
    waypoint's departure instant, "arrival @ <attr>" when it lands near an
    arrival instant instead, None otherwise. Departure wins ties/close
    calls only when it's the strictly closer of the two -- confirmed
    against a real capture (task 6227a076..., bot 200): the rotation at
    06:41:07.459 lands 5.02s after the "pps -> pps" phase's own departure
    instant (right after "lift down @ pps"), and the nearest arrival
    (at "highway", not a key waypoint) is a closer-but-irrelevant 3.16s
    away -- this is the "just came out of pps" rotation the departure
    check exists to catch, which the arrival-only version used to
    attribute to that unrelated non-key arrival and silently drop to
    "minor".
    """
    arrival_attr, arrival_delta = nearest_phase_attr(rotation_event.timestamp, phases)
    departure_attr, departure_delta = _nearest_key_departure_attr(rotation_event.timestamp, phases)
    arrival_ok = arrival_attr in KEY_WAYPOINT_ATTRS and arrival_delta is not None and arrival_delta <= window_seconds
    departure_ok = departure_delta is not None and departure_delta <= window_seconds
    if departure_ok and (not arrival_ok or departure_delta < arrival_delta):
        return f"{departure_attr} exit"
    if arrival_ok:
        return f"arrival @ {arrival_attr}"
    return None


def classify_rotation_significance(
    rotation_event: RotationEvent,
    phases: list[dict],
    window_seconds: float = MAJOR_ROTATION_WINDOW_SECONDS,
) -> str:
    return "major" if label_rotation_context(rotation_event, phases, window_seconds) is not None else "minor"


def annotate_event_context(trace) -> None:
    """Mutates trace.lift_events/trace.rotation_events/
    trace.fork_adjustment_events in place, adding context_label/
    significance/label -- call once, after all three have already been
    attached (see api/routes.py)."""
    phases = trace.phase_durations()
    for le in trace.lift_events:
        le.context_label = label_lift_context(le, phases)
    for re_ in trace.rotation_events:
        label = label_rotation_context(re_, phases)
        re_.significance = "major" if label is not None else "minor"
        re_.context_label = label
    for fe in trace.fork_adjustment_events:
        fe.label = label_fork_adjustment(fe, phases)
