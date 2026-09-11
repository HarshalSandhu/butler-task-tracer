"""Charge-cycle timing breakdown for chargetask -- confirmed against two
real traces: 001d1a82-f75f-4c1d-9568-2dd5ba33ecfb (HTM, bot 206) and
165500f6-d46e-43f6-8fa6-ee1d7c691a45 (VTM, bot 214):

  assigned (Starting TaskId)
    -> reached charger_reinit (approach/staging point)
    -> reached charger (docked)
    -> charging_started (chargetaskrec status, lands right at dock arrival)
    -> charging_complete (chargetaskrec status)
    -> [return dispatched: a NEW SubTask_list with goto_parking_point]
    -> reached charger_reinit again (backing out of the dock)
    -> "parked" -- confirmed this is NOT a dedicated parking attr; the
       task's own goto_parking_point subtask lands the bot back at
       ordinary relay/storable waypoints, reusing existing infrastructure
       rather than a distinct parking zone. HTM uses relay_storable_io_point
       /relay_storable for this; VTM uses its own ttp_storable_io_point/
       ttp_storable -- both are accepted here (same gap as the fork-
       adjustment pick/drop labeling had before this attr set was widened).

chargetaskrec's status lines come in two shapes on the same line format
(`Updating status to X for taskid ...`): an early pending-state tuple
(`{pending,assigned}`, `{pending,started}`) and later plain atoms
(`reached_reinit_point`, `charging_started`, `charging_complete`) -- only
the atom values are meaningful for this breakdown.

Confirmed real anomaly (VTM trace 165500f6...): `charging_complete` fired
TWICE, ~2h10m apart, with a `charger_reinit` and a parking-attr arrival
after each. Bounding the return-leg search to a short window after the
*first* `charging_complete`/its own `charger_reinit` return (rather than
"last occurrence anywhere in the trace") is what keeps `parked_at` from
jumping across that gap to the second, unrelated cycle -- that gap is
still unexplained and worth investigating further, but this at least
avoids reporting a nonsensical multi-hour "return travel time" for it.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.models import ChargeTiming
from app.parsers.lift_events import nearest_telemetry_reading
from app.parsers.line_parser import ParsedLine

_STATUS_RE = re.compile(
    r"Updating status to (?P<status>[a-z_]+) for taskid \{chargetask,<<\"(?P<task_id>[^\"]+)\">>"
)
_ASSIGNED_MARKER = "Starting TaskId:"
_RETURN_DISPATCH_MARKER = "goto_parking_point"
_DISPATCH_MARKER = "SubTask_list:"

# Confirmed real, found automatically (not by manual grep) across two
# independent chargetasks (87e760ef-1639-4b02-9c06-7efcefc8148d,
# 16efa65e-a65d-4fcb-83f3-0fd9bfb12e52, both bot 210) and 6 others via
# `zgrep -h -E 'Received graceful stop ack.*chargetask.*graceful_stop_
# reason => <<"api_stop">>'` across the fleet's own logs: an API-issued
# stop lands on this line, and `charging_complete` fires only ~3-4s
# later in both confirmed cases -- i.e. this is what actually TRIGGERED
# charging to end, not an independent, unrelated event. Neither
# `charging_complete` alone nor the chargetaskrec status lines carry any
# indication of *why* charging stopped (reached full charge vs. an
# operator/API cutting it short) -- this line is the only place that
# distinction exists in the log at all.
_GRACEFUL_STOP_RE = re.compile(
    r'Received graceful stop ack, TaskId = \{chargetask,<<"[^"]+">>.*?'
    r'graceful_stop_reason => <<"(?P<reason>[^"]+)">>'
)

# How close a battery-telemetry reading needs to land to reached_charger_at/
# charging_complete_at to count as "the level at that instant" -- these
# readings arrive roughly every 0.2-1s in every real capture seen, so 30s
# is a generous margin that only fails to find a reading during a genuine
# telemetry gap, not ordinary sampling spacing.
_BATTERY_LOOKUP_TOLERANCE_SECONDS = 30.0


def attach_battery_levels(timing: ChargeTiming, battery_readings: list[tuple[datetime, float]]) -> None:
    """Mutates `timing` in place with battery_pct_at_charger_arrival/
    battery_pct_at_charging_complete, nearest reached_charger_at/
    charging_complete_at respectively. `battery_readings` should already
    be scoped to this task's own bot_id (see lift_events.py's
    parse_battery_telemetry) -- called from api/routes.py's
    _apply_lift_rotation_lines, reusing the SAME #recv lines already
    fetched for lift/rotation enrichment, no extra SSH round trip.
    """
    if timing.reached_charger_at is not None:
        timing.battery_pct_at_charger_arrival = nearest_telemetry_reading(
            battery_readings, timing.reached_charger_at, _BATTERY_LOOKUP_TOLERANCE_SECONDS
        )
    if timing.charging_complete_at is not None:
        timing.battery_pct_at_charging_complete = nearest_telemetry_reading(
            battery_readings, timing.charging_complete_at, _BATTERY_LOOKUP_TOLERANCE_SECONDS
        )

_CHARGER_REINIT_ATTR = "charger_reinit"
_CHARGER_ATTR = "charger"
_PARKING_CANDIDATE_ATTRS = {"relay_storable_io_point", "relay_storable", "ttp_storable_io_point", "ttp_storable"}

# How long after backing out to charger_reinit a parking-attr arrival still
# counts as "this same return leg" -- confirmed real return legs settle
# within ~20s of backing out (both HTM and VTM traces); generous margin
# above that without being wide enough to reach into an unrelated, much
# later charge cycle on the same task_id (the real anomaly above was ~2h10m
# away, nowhere close to this window).
_RETURN_LEG_WINDOW_SECONDS = 90


def build_charge_timing(parsed: list[ParsedLine]) -> ChargeTiming:
    """`parsed` should be every line matching this chargetask's task_id
    (same grep as build_trace uses) -- chargetaskrec's status lines and
    the goto_parking_point re-dispatch both restate the task_id inline, so
    a plain task_id grep already covers everything this needs.
    """
    timing = ChargeTiming()
    charger_reinit_hits: list[datetime] = []
    parking_hits: list[datetime] = []

    for p in parsed:
        if timing.assigned_at is None and _ASSIGNED_MARKER in p.message:
            timing.assigned_at = p.timestamp

        if (
            timing.return_dispatched_at is None
            and _DISPATCH_MARKER in p.message
            and _RETURN_DISPATCH_MARKER in p.message
        ):
            timing.return_dispatched_at = p.timestamp

        if timing.graceful_stop_at is None:
            gm = _GRACEFUL_STOP_RE.search(p.message)
            if gm:
                timing.graceful_stop_at = p.timestamp
                timing.graceful_stop_reason = gm.group("reason")

        m = _STATUS_RE.search(p.message)
        if m:
            status = m.group("status")
            if status == "charging_started" and timing.charging_started_at is None:
                timing.charging_started_at = p.timestamp
            elif status == "charging_complete" and timing.charging_complete_at is None:
                timing.charging_complete_at = p.timestamp
            continue

        attr_match = re.search(r"reached \{-?\d+,-?\d+\} \(attr=(?P<attr>\w+)\)", p.message)
        if not attr_match:
            continue
        attr = attr_match.group("attr")

        if attr == _CHARGER_REINIT_ATTR:
            charger_reinit_hits.append(p.timestamp)
        elif attr == _CHARGER_ATTR and timing.reached_charger_at is None:
            timing.reached_charger_at = p.timestamp
        elif attr in _PARKING_CANDIDATE_ATTRS:
            parking_hits.append(p.timestamp)

    if charger_reinit_hits:
        timing.reached_charger_reinit_at = charger_reinit_hits[0]

    if timing.charging_complete_at is not None:
        after_complete = [t for t in charger_reinit_hits if t > timing.charging_complete_at]
        if after_complete:
            timing.return_reached_charger_reinit_at = after_complete[0]

    if timing.return_reached_charger_reinit_at is not None:
        window_end = timing.return_reached_charger_reinit_at + timedelta(seconds=_RETURN_LEG_WINDOW_SECONDS)
        in_window = [
            t for t in parking_hits if timing.return_reached_charger_reinit_at <= t <= window_end
        ]
        if in_window:
            timing.parked_at = in_window[-1]

    return timing
