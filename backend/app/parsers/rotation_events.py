"""HTM in-place rotation time -- the "bot reaches the io point, then has to
turn to face it" delay the user asked to have accounted for, since it's
real physical time that doesn't otherwise show up as a distinct phase.

There's no dedicated "rotation took Nms" log line (unlike the fork-lift's
`finaltime_with_buffer`) -- rotation is computed deep inside COWHCA
path-planning and only surfaces indirectly, embedded in the planned-path
dump `navigator_agent:handle_event`/`recalculate_path` log on every
re-plan:

    butler_id=200 Got goal pathlist = [
      {coordinate_movement_info,{24,44},683367,683367,683367,687067,
       [...],{24,44},{24,44},west,undefined,0,rest,0,undefined,west,false,1},
      {coordinate_movement_info,{24,44},683367,687067,687067,689008,
       [...],{24,44},{24,44},north,undefined,0,turn_step,0,undefined,north,false,2},
      ...
    ], StartTime: {{2,1,10},{4,33,50}}

Field decode (confirmed by cross-checking 10 consecutive real entries: the
3rd numeric field of every entry equals the 4th numeric field of the entry
immediately before it, i.e. they chain into one continuous timeline):

    {coordinate_movement_info, Coord, N1, StepStartMs, _StepStartMs2,
     StepEndMs, SpanList, FromCoord, ToCoord, Direction, undefined,
     _N2, StepType, ...}

  StepEndMs - StepStartMs is that step's own duration in milliseconds.
  StepType is one of rest/turn_step/acceleration_step/top_speed_step/
  deceleration_step. Only turn_step entries represent in-place rotation.

What this does NOT establish (be honest about the gap, same as
lift_events' telemetry-vs-estimate distinction): StepStartMs/StepEndMs are
relative to whatever internal clock the path planner used when this plan
was computed, not wall-clock time -- there's no confirmed decode of the
`StartTime` tuple at the end of the line to convert them to an absolute
timestamp. Every RotationEvent below is therefore anchored to the pathlist
LINE's own (real, absolute) log timestamp, not the precise instant the turn
physically executed -- same epistemic status as an "estimated_buffer" lift
correction: a reasonable, task-window-scoped approximation, not ground
truth to the millisecond. Always Confidence.HEURISTIC for this same reason,
and because these lines never restate a task_id (attribution is by
butler_id + falling inside the task's time window, exactly like lift
events).

A bot re-plans its path repeatedly as it moves (traffic, intersections),
so the same physical turn can appear in several successive pathlist
snapshots as "still upcoming" before it actually happens. Deduping by
(coordinate, step index) and keeping only the LAST-seen duration for that
slot is a deliberate choice to avoid inflating a task's total rotation
time by counting the same turn multiple times.

GROUND TRUTH, confirmed after the above: the AGV's own VDA5050 state
stream reports its actual heading directly --
`agvPosition.theta` in the same `#recv` lines lift_events.py already reads
`liftHeight` from:

    butler_id=210 #recv: ... Payload = #{..., <<"agvPosition">> => #{
      <<"liftHeight">> => 0.251, ..., <<"theta">> => 1.57,
      <<"x">> => 104.96, <<"y">> => 99.57}, ...}

Confirmed real against task ef3d2ee1-c0e7-498e-9824-c32f34a3c7a3: theta
genuinely steps through quantized values (0, +-pi/2, pi -- quarter/half
turns) as the bot executes an in-place turn, including one on the
highway -> relay_storable_io_point leg that the turn_step reconstruction
alone classified as barely worth noting. This is a real physical
measurement, not an estimate -- exactly the same epistemic upgrade
lift_events.py's telemetry path is over its buffer estimate -- so it's
preferred whenever available. `coordinate` comes from the same reading's
agvPosition.x/y (not a grid cell like the planned-path estimate's, but the
AGV's own real-valued position at that instant).

Because both sources can describe the *same* physical turn, a turn_step
estimate is dropped whenever a telemetry-confirmed rotation lands within
_TELEMETRY_CONFIRM_WINDOW_SECONDS of it -- otherwise a single real rotation
would double-count into two rows.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from app.models import RotationEvent
from app.parsers.line_parser import ParsedLine

_PATHLIST_FUNCTION_NAMES = {"handle_event", "recalculate_path"}

_STEP_RE = re.compile(
    r"\{coordinate_movement_info,\{(?P<x>-?\d+),(?P<y>-?\d+)\},"
    r"\d+,(?P<step_start>\d+),\d+,(?P<step_end>\d+),"
    r"\[.*?\],"
    r"\{-?\d+,-?\d+\},\{-?\d+,-?\d+\},"
    r"\w+,undefined,\d+,"
    r"(?P<step_type>turn_step|rest|acceleration_step|top_speed_step|deceleration_step),"
    r"\d+,undefined,\w+,(?:true|false),(?P<idx>\d+)\}"
)

_BOT_ID_RE = re.compile(r"butler_id=(?P<bot_id>\d+)")

# Same #recv lines grep_bot_lift_lines already matches (via "liftHeight") --
# reusing the identical anchor keeps this parseable from that same fetch.
# theta is immediately followed by x, y in the same agvPosition block (see
# lift_events.py's _XY_RE note on map key ordering), so this single match
# also gives ground-truth coordinate for telemetry-confirmed rotations,
# which previously had none at all.
_THETA_RE = re.compile(
    r'butler_id=(?P<bot_id>\d+) #recv:.*?<<"theta">> => (?P<theta>-?[\d.]+),'
    r'<<"x">> => (?P<x>-?[\d.]+),<<"y">> => (?P<y>-?[\d.]+)'
)

# ~17 degrees -- comfortably below the real observed turn sizes (~pi/2,
# ~pi) while filtering out sensor/reporting jitter at a held heading.
_THETA_CHANGE_THRESHOLD_RAD = 0.3

# A telemetry-confirmed rotation within this many seconds of a turn_step
# estimate is treated as the same physical turn -- the turn_step is then
# dropped in favor of the ground-truth telemetry event.
_TELEMETRY_CONFIRM_WINDOW_SECONDS = 5.0

# Real turn_step/theta-confirmed rotations observed across every capture
# this session topped out around ~2.6s. Confirmed real bug (chargetask,
# VTM bot 214): during a long stationary/charging pause, telemetry sampling
# goes sparse, so two consecutive readings can be minutes apart -- if the
# heading also happened to differ between them (e.g. one reading from
# before parking, the next from well after), that gap gets misread as one
# continuous multi-minute "rotation". A generous cap well above any real
# turn (but far below "the bot was stationary for 10+ minutes") discards
# those without needing to model idle/charging periods explicitly.
_MAX_PLAUSIBLE_ROTATION_MS = 8000.0


def _build_turn_step_events(parsed: list[ParsedLine]) -> list[RotationEvent]:
    latest_by_slot: dict[tuple[int, int, str], RotationEvent] = {}

    for p in parsed:
        if p.function not in _PATHLIST_FUNCTION_NAMES:
            continue
        bot_match = _BOT_ID_RE.search(p.message)
        if not bot_match:
            continue
        bot_id = bot_match.group("bot_id")

        for step in _STEP_RE.finditer(p.message):
            if step.group("step_type") != "turn_step":
                continue
            duration_ms = int(step.group("step_end")) - int(step.group("step_start"))
            if duration_ms <= 0:
                continue
            slot = (int(step.group("x")), int(step.group("y")), step.group("idx"))
            latest_by_slot[slot] = RotationEvent(
                bot_id=bot_id,
                timestamp=p.timestamp,
                coordinate=(int(step.group("x")), int(step.group("y"))),
                duration_ms=float(duration_ms),
                method="planned_path_estimate",
            )

    return list(latest_by_slot.values())


def parse_theta_telemetry(lines: list[ParsedLine]) -> dict[str, list[tuple[datetime, float, float, float]]]:
    """{bot_id: [(timestamp, theta_radians, x, y), ...]}, sorted per bot --
    same #recv source as lift_events.parse_lift_telemetry, reading theta
    and the agvPosition x/y alongside it."""
    out: dict[str, list[tuple[datetime, float, float, float]]] = {}
    for p in lines:
        m = _THETA_RE.search(p.message)
        if not m:
            continue
        out.setdefault(m.group("bot_id"), []).append(
            (p.timestamp, float(m.group("theta")), float(m.group("x")), float(m.group("y")))
        )
    for bot_id in out:
        out[bot_id].sort(key=lambda row: row[0])
    return out


def _theta_delta(a: float, b: float) -> float:
    """Smallest angular difference between two headings, accounting for
    the -pi/pi wraparound (e.g. 3.10 -> -3.10 is a tiny turn, not ~6.2 rad)."""
    d = abs(a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


def build_theta_rotation_events(
    telemetry_for_bot: list[tuple[datetime, float, float, float]], bot_id: str
) -> list[RotationEvent]:
    """One RotationEvent per real, meaningful heading change between
    consecutive telemetry readings -- ground truth, timestamped/duration'd
    directly from the AGV's own reports. `coordinate` is the AGV's own
    (x, y) at the completing reading (ts2), same telemetry line theta2
    came from."""
    events = []
    for (ts1, theta1, _x1, _y1), (ts2, theta2, x2, y2) in zip(telemetry_for_bot, telemetry_for_bot[1:]):
        if _theta_delta(theta1, theta2) < _THETA_CHANGE_THRESHOLD_RAD:
            continue
        duration_ms = (ts2 - ts1).total_seconds() * 1000
        if duration_ms <= 0 or duration_ms > _MAX_PLAUSIBLE_ROTATION_MS:
            continue
        events.append(
            RotationEvent(
                bot_id=bot_id,
                timestamp=ts2,
                coordinate=(x2, y2),
                duration_ms=duration_ms,
                method="telemetry",
            )
        )
    return events


def build_rotation_events(parsed: list[ParsedLine]) -> list[RotationEvent]:
    """`parsed` should be every line matching grep_bot_rotation_lines for
    one bot_id, already restricted (by the caller) to one task's padded
    time window -- see api/routes.py's _attach_lift_events for the
    equivalent lift-event pattern this mirrors.
    """
    turn_step_events = _build_turn_step_events(parsed)

    theta_telemetry = parse_theta_telemetry(parsed)
    theta_events: list[RotationEvent] = []
    for bot_id, readings in theta_telemetry.items():
        theta_events.extend(build_theta_rotation_events(readings, bot_id))

    def _confirmed_by_telemetry(estimate: RotationEvent) -> bool:
        return any(
            estimate.bot_id == te.bot_id
            and abs((estimate.timestamp - te.timestamp).total_seconds()) <= _TELEMETRY_CONFIRM_WINDOW_SECONDS
            for te in theta_events
        )

    kept_estimates = [e for e in turn_step_events if not _confirmed_by_telemetry(e)]

    return sorted(theta_events + kept_estimates, key=lambda e: e.timestamp)
