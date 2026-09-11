"""Ground-truth reconstruction for fork-lift/tote-transfer timing -- HTM's
`simultaneousForkLift` and VTM's `setForkHeight`/`tote_load`/`tote_unload`
(see _VTM_FORK_HEIGHT_ORDER_RE/_VTM_TOTE_ORDER_RE below for the VTM side;
entirely different order vocabulary from HTM, confirmed real against task
4e20786c-dec3-4545-b2ce-4948c1819f4e, bot 214).

`simultaneousForkLift` is sent with `blockingType=NONE` -- the one AGV
command that isn't gated on physical completion (every other command:
pick, drop, forkHeight adjust, blocks until the AGV reports the action
actually finished). The log records the premature "completed" line the
instant the AGV acks *receiving* the order, not when the fork physically
reaches height -- in one of TWO differently-worded forms depending on
which subtask issued the order: "Fork height adjustment completed for
simultaneous_fork_lift_to_maxdown_height subtask" (the maxdown-settle
case) or "Fork height adjustment completed during parallel navigation"
(issued via `compute_parallel_lift_goto_barcode`, i.e. a lift that happens
*while the bot is already traveling* -- confirmed real, task
da1cfdc4-5f0d-49c5-8678-157d9f4675a3, bot 209: `Order =
{simultaneousForkLift, #{..., fork_height => 880, ...}}` at 11:45:25.858,
completed-notice at 11:45:29.564, worded the second way. Both are the
exact same premature-completion phenomenon and need the exact same
telemetry correction below -- _PREMATURE_COMPLETE_RE matches either
wording.

Two ways to reconstruct the real completion time, in priority order:

  1. Ground truth: the AGV's own periodically-reported `liftHeight` (from
     its VDA5050 state stream) crosses within tolerance of the commanded
     target height, at or after the order was sent. Confirmed against a
     real capture: a fork genuinely descending 878mm -> 472mm -> 298mm ->
     262mm, settling within tolerance of a 260mm target ~4.4s after the
     log's premature "completed" line -- this is a real signal, not just
     a theoretical ideal, and is used whenever it's available.
  2. Fallback: the system's own `vertical_movement_utils:
     simultaneous_lift_time_for_fork` log line, which computes exactly how
     long the physical travel *should* take (`finaltime_with_buffer`) --
     used only when (1) finds no *post*-completion-flag crossing. This
     isn't only a simulator/telemetry-quality issue: it also happens
     legitimately when the fork was already within tolerance *before* the
     order was even sent (seen in the same real capture, a different lift
     event on the same bot) -- there's no later crossing to observe in
     that case since the AGV never needed to move, so the buffer-time
     estimate is the only signal available either way.

None of these lines restate the task's own id/MainTaskKey -- attribution to
a specific task is by butler_id + falling inside that task's own time
window (same idea as parsers/correlation.py's orphan-event heuristic),
which is the caller's job (see ssh/executor.py's grep_bot_lift_lines and
its use in api/routes.py). That's also why every LiftEvent this module
produces is Confidence.HEURISTIC, never EXACT.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.models import ForkAdjustmentEvent, LiftEvent
from app.parsers.line_parser import ParsedLine

_ORDER_FUNCTION = "pub_order"  # module:function is gmc_mqtt_agv_communicator:pub_order -- line_parser
# already splits that into ParsedLine.function, so it's checked there, not
# matched inside the message text (a prior version of this regex tried to
# match the literal substring "pub_order" against the message and silently
# never matched anything, since that text lives in the module:function
# prefix that line_parser strips off).
_ORDER_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+).*Order = \{simultaneousForkLift,#\{.*?fork_height => (?P<fork_height>\d+)"
)
_PREMATURE_COMPLETE_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) Fork height adjustment completed "
    r"(?:for simultaneous_fork_lift_to_maxdown_height subtask|during parallel navigation)"
)
# Split out from the combined pattern above specifically to tell the two
# wordings apart -- see build_lift_events' maxdown-noop suppression below,
# which must ONLY apply to an EXPLICIT `simultaneous_fork_lift_to_
# maxdown_height` settle order, never to a "during parallel navigation"
# lift (issued via compute_parallel_lift_goto_barcode -- a real functional
# lift mid-travel, e.g. raising to 880mm to clear an aisle, not a maxdown
# settle, even on the rare occasion its target height happens to coincide
# with a maxdown value).
_MAXDOWN_SETTLE_COMPLETE_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) Fork height adjustment completed "
    r"for simultaneous_fork_lift_to_maxdown_height subtask"
)
_TRAVEL_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) fork travel (?P<from_mm>\d+) -> (?P<to_mm>\d+) mm "
    r"\(clamped to (?P<clamped_mm>\d+)\), time=(?P<time_ms>[\d.]+) ms, "
    r"finaltime_with_buffer=(?P<buffer_ms>[\d.]+) ms"
)
_LIFT_HEIGHT_RE = re.compile(r'butler_id=(?P<bot_id>\d+) #recv:.*?"liftHeight">> => (?P<height_m>[\d.]+)')

# Same #recv agvPosition block liftHeight/theta come from -- confirmed real:
# {"liftHeight":...,"mapId":...,"positionInitialized":...,"theta":...,
#  "x":...,"y":...} always in this order (Erlang prints map keys sorted),
# so a single leftmost regex match is always agvPosition's own x/y, never
# one of the (also-present) per-node x/y pairs inside nodeStates further
# along in the same line -- those come later in the message string.
_XY_RE = re.compile(r'butler_id=(?P<bot_id>\d+) #recv:.*?<<"x">> => (?P<x>-?[\d.]+),<<"y">> => (?P<y>-?[\d.]+)')

# Same #recv payload, a different top-level field (batteryState.
# batteryCharge, a 0-100 percentage) -- confirmed real (chargetask
# 87e760ef-1639-4b02-9c06-7efcefc8148d, bot 210): 57.0% right at
# reached_charger_at, 70.0% right at charging_complete_at, a real,
# meaningful rise over the charge cycle. Used by charge_timing.py to
# report battery level at charger arrival/charging-complete.
_BATTERY_CHARGE_RE = re.compile(r'butler_id=(?P<bot_id>\d+) #recv:.*?<<"batteryCharge">> => (?P<battery_pct>[\d.]+)')

# Confirmed real (task 6227a076-190b-42dc-a957-f5523dbc2f94, bot 200): unlike
# simultaneousForkLift, these two orders carry the target height AND tote_id
# directly, and have a real completion confirmation ("Received
# htm_load_tote_finished for tote ...") -- ground truth, no telemetry
# inference needed at all, and the action name itself is the label (no
# nearest-waypoint guessing required either).
_TOTE_TRANSFER_LABELS = {"htm_load_tote": "pick", "htm_unload_tote": "drop"}
_TOTE_ORDER_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+).*Order = \{(?P<action>htm_load_tote|htm_unload_tote),#\{"
    r'.*?height => (?P<height>\d+),tote_id => <<"(?P<tote_id>[^"]+)">>'
)
_TOTE_FINISHED_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) Received (?P<action>htm_load_tote|htm_unload_tote)_finished "
    r'for tote <<"(?P<tote_id>[^"]+)">>'
)
# A load/unload order and its completion land within a few seconds of each
# other in the real capture (order 06:41:37.801 -> finished 06:41:39.559,
# ~1.8s); generous margin above that without risking pairing across two
# unrelated tote transfers on the same bot. Also generous enough for VTM's
# tote_load/tote_unload (below), whose own real completions land 9-11s
# after the order (confirmed real, task 4e20786c..., bot 214).
_TOTE_TRANSFER_LOOKAHEAD_SECONDS = 30.0

# VTM's fork-height/tote-transfer vocabulary -- entirely different orders
# from HTM's (simultaneousForkLift, htm_load_tote/htm_unload_tote above),
# confirmed real against task 4e20786c-dec3-4545-b2ce-4948c1819f4e (bot
# 214): `setForkHeight` pre-positions the fork (often *while the bot is
# still traveling* to the next waypoint -- confirmed: order sent
# 14:34:51.546, but the bot's own goto_barcode move order goes out at
# 14:34:52.626, ~1s later, well before the fork settles), and `tote_load`/
# `tote_unload` are the stationary, in-place pick/drop actions themselves
# (carrying the target height + tote_id directly, exactly like HTM's
# htm_load_tote/htm_unload_tote).
_VTM_FORK_HEIGHT_ORDER_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+).*Order = \{setForkHeight,#\{.*?fork_height => (?P<fork_height>\d+)"
)
_VTM_TOTE_ORDER_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+).*Order = \{(?P<action>tote_load|tote_unload),#\{"
    r'.*?height => (?P<height>\d+),tote_id => <<"(?P<tote_id>[^"]+)">>'
)
_VTM_TOTE_LABELS = {"tote_load": "pick", "tote_unload": "drop"}

# Unlike HTM, VTM has no dedicated "Fork height adjustment completed"/
# "Received X_finished" log line at all -- the only completion signal is
# the AGV's own VDA5050 actionStates stream (the same #recv lines already
# fetched for liftHeight/theta), keyed by an actionId of the form
# "<action_type>_<uuid>" with its own actionStatus (WAITING -> RUNNING ->
# FINISHED). Confirmed real (task 4e20786c...): setForkHeight's FINISHED
# fires the instant the order is acked -- 14:34:52.381 -- while liftHeight
# telemetry doesn't cross within tolerance of the 1300mm target until
# 14:34:55.175, ~2.8s later. The SAME premature-completion pattern
# simultaneousForkLift has, corrected the same way (telemetry crossing).
# tote_load/tote_unload's FINISHED, by contrast, genuinely waits for the
# real action (confirmed: tote_unload's FINISHED at 14:35:25.735 lines up
# with liftHeight actually reaching ~877mm, within a few mm of the 850mm
# order target) -- so it's used directly as the real completion instant,
# no telemetry correction needed, same epistemic status as HTM's
# "Received htm_unload_tote_finished".
_VTM_ACTION_STATE_RE = re.compile(
    r'butler_id=(?P<bot_id>\d+) #recv:.*?<<"actionId">> => <<"(?P<action_type>forkHeight|toteLoad|toteUnload)_'
    r'(?P<action_uuid>[0-9a-fA-F-]+)">>,<<"actionStatus">> => <<"(?P<status>WAITING|RUNNING|FINISHED)">>'
)

DEFAULT_TOLERANCE_MM = 10.0
# Order -> premature-complete -> travel-time line all land within a couple
# seconds of each other in every real capture seen so far; consecutive,
# unrelated lift orders on the same bot are spaced tens of seconds apart, so
# this window can't accidentally cross into a different lift event.
_ORDER_LOOKBACK_SECONDS = 6.0
_TRAVEL_LOOKAHEAD_SECONDS = 2.0

# Confirmed against a real pickup/drop cycle (task 70f0fa18...): idle/maxdown
# height reads ~252mm, target is always ~250mm for a maxdown order -- a ~2mm
# gap that must NOT register as a real "down" move. A raised height before
# pickup/handoff (~417-548mm observed) against the same ~250mm target is
# unambiguously a real move. 15mm sits comfortably between the two.
_DIRECTION_TOLERANCE_MM = 15.0


def classify_direction(
    pre_height_mm: float | None,
    target_mm: float | None,
    tolerance_mm: float = _DIRECTION_TOLERANCE_MM,
) -> str | None:
    """"down" if the fork was measurably above target before the order,
    "up" if measurably below, None if there's no telemetry to compare
    against or the fork was already essentially at target (a same-height
    confirmation, not a real move)."""
    if pre_height_mm is None or target_mm is None:
        return None
    delta = target_mm - pre_height_mm
    if delta < -tolerance_mm:
        return "down"
    if delta > tolerance_mm:
        return "up"
    return None


def _height_before(telemetry_for_bot: list[tuple[datetime, float]], before: datetime) -> float | None:
    """Last reading strictly before `before` -- telemetry_for_bot is sorted
    ascending by parse_lift_telemetry."""
    height: float | None = None
    for ts, h in telemetry_for_bot:
        if ts >= before:
            break
        height = h
    return height


def parse_agv_coordinates(lines: list[ParsedLine]) -> dict[str, list[tuple[datetime, float, float]]]:
    """{bot_id: [(timestamp, x, y), ...]}, sorted per bot -- same #recv
    lines parse_lift_telemetry reads, just a different field of the same
    agvPosition block."""
    out: dict[str, list[tuple[datetime, float, float]]] = {}
    for p in lines:
        m = _XY_RE.search(p.message)
        if not m:
            continue
        out.setdefault(m.group("bot_id"), []).append(
            (p.timestamp, float(m.group("x")), float(m.group("y")))
        )
    for bot_id in out:
        out[bot_id].sort(key=lambda triple: triple[0])
    return out


def _xy_at_or_before(coords_for_bot: list[tuple[datetime, float, float]], at: datetime) -> tuple[float, float] | None:
    """Latest (x, y) at/before `at` -- inclusive (unlike _height_before)
    since callers pass an event's own timestamp, itself one of these
    readings, and want that exact position rather than the one prior."""
    xy: tuple[float, float] | None = None
    for ts, x, y in coords_for_bot:
        if ts > at:
            break
        xy = (x, y)
    return xy


def parse_lift_telemetry(lines: list[ParsedLine]) -> dict[str, list[tuple[datetime, float]]]:
    """{bot_id: [(timestamp, liftHeight_mm), ...]}, sorted per bot."""
    out: dict[str, list[tuple[datetime, float]]] = {}
    for p in lines:
        m = _LIFT_HEIGHT_RE.search(p.message)
        if not m:
            continue
        out.setdefault(m.group("bot_id"), []).append(
            (p.timestamp, float(m.group("height_m")) * 1000.0)
        )
    for bot_id in out:
        out[bot_id].sort(key=lambda pair: pair[0])
    return out


def parse_battery_telemetry(lines: list[ParsedLine]) -> dict[str, list[tuple[datetime, float]]]:
    """{bot_id: [(timestamp, battery_pct), ...]}, sorted per bot -- same
    #recv source as parse_lift_telemetry, just reading batteryState.
    batteryCharge instead."""
    out: dict[str, list[tuple[datetime, float]]] = {}
    for p in lines:
        m = _BATTERY_CHARGE_RE.search(p.message)
        if not m:
            continue
        out.setdefault(m.group("bot_id"), []).append((p.timestamp, float(m.group("battery_pct"))))
    for bot_id in out:
        out[bot_id].sort(key=lambda pair: pair[0])
    return out


def nearest_telemetry_reading(
    telemetry_for_bot: list[tuple[datetime, float]], at: datetime, tolerance_seconds: float
) -> float | None:
    """Closest reading to `at` (before OR after -- unlike _height_before,
    which only looks backward) within `tolerance_seconds`, else None.
    Used for battery level, where the exact reading nearest an instant
    matters more than a strict "last known value before it" semantic."""
    best_value: float | None = None
    best_delta: float | None = None
    for ts, value in telemetry_for_bot:
        delta = abs((ts - at).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_value = value
    if best_delta is not None and best_delta <= tolerance_seconds:
        return best_value
    return None


def find_telemetry_completion(
    telemetry: list[tuple[datetime, float]],
    after: datetime,
    target_mm: float,
    tolerance_mm: float = DEFAULT_TOLERANCE_MM,
) -> datetime | None:
    """First telemetry timestamp at/after `after` where the reported height
    is within tolerance of target -- the real ground-truth completion.
    None if it never crosses (see module docstring)."""
    for ts, height_mm in telemetry:
        if ts < after:
            continue
        if abs(height_mm - target_mm) <= tolerance_mm:
            return ts
    return None


def build_lift_events(lines: list[ParsedLine]) -> list[LiftEvent]:
    """`lines` should already be scoped to one bot's time window (see
    ssh/executor.py's grep_bot_lift_lines) -- this module has no way to
    disambiguate between two different tasks on the same bot on its own;
    that scoping is the caller's responsibility.
    """
    telemetry = parse_lift_telemetry(lines)
    coordinates = parse_agv_coordinates(lines)

    orders: list[tuple[datetime, str, float]] = []
    vtm_orders: list[tuple[datetime, str, float]] = []
    # is_maxdown_settle: True only for the EXPLICIT "for simultaneous_fork_
    # lift_to_maxdown_height subtask" wording -- see the maxdown-noop
    # suppression below, which must never apply to a "during parallel
    # navigation" completion (a real functional lift, not a settle).
    completes: list[tuple[datetime, str, bool]] = []
    travels: list[tuple[datetime, str, float]] = []
    # actionStates repeats the SAME actionStatus across several consecutive
    # #recv snapshots (confirmed real: one forkHeight FINISHED appeared 4
    # times, ~9ms apart) -- keyed by (bot_id, action_uuid) so only the
    # FIRST sighting of a given action's FINISHED becomes a `completes`
    # entry, not four duplicate LiftEvents for one real lift.
    seen_vtm_finished: set[tuple[str, str]] = set()

    for p in lines:
        if p.function == _ORDER_FUNCTION:
            m = _ORDER_RE.search(p.message)
            if m:
                orders.append((p.timestamp, m.group("bot_id"), float(m.group("fork_height"))))
                continue
            m = _VTM_FORK_HEIGHT_ORDER_RE.search(p.message)
            if m:
                order = (p.timestamp, m.group("bot_id"), float(m.group("fork_height")))
                orders.append(order)
                vtm_orders.append(order)
            continue
        m = _PREMATURE_COMPLETE_RE.search(p.message)
        if m:
            is_maxdown_settle = _MAXDOWN_SETTLE_COMPLETE_RE.search(p.message) is not None
            completes.append((p.timestamp, m.group("bot_id"), is_maxdown_settle))
            continue
        m = _VTM_ACTION_STATE_RE.search(p.message)
        if m and m.group("action_type") == "forkHeight" and m.group("status") == "FINISHED":
            # HTM's OWN simultaneousForkLift rides the SAME "forkHeight_..."
            # actionId/actionStatus VDA5050 stream (confirmed real: an HTM
            # capture's #recv lines carry `actionId => forkHeight_c3213...`
            # too) -- without this check, every HTM lift would double-count
            # (once via _PREMATURE_COMPLETE_RE, once via this actionStates
            # match), inflating a real 2-event fixture to 7. Only accept
            # this as a genuine VTM completion when a real `setForkHeight`
            # order (specifically -- not just any order) for this bot
            # actually preceded it -- true for VTM (order->FINISHED is <1s
            # in every real capture seen), never true for HTM (which never
            # sends setForkHeight at all, only simultaneousForkLift).
            bot_id = m.group("bot_id")
            has_recent_vtm_order = any(
                bid == bot_id and 0 <= (p.timestamp - ts).total_seconds() <= _ORDER_LOOKBACK_SECONDS
                for ts, bid, _ in vtm_orders
            )
            key = (bot_id, m.group("action_uuid"))
            if has_recent_vtm_order and key not in seen_vtm_finished:
                seen_vtm_finished.add(key)
                # VTM has no equivalent "maxdown settle" subtask name at all
                # (see module docstring) -- never eligible for the
                # maxdown-noop suppression below.
                completes.append((p.timestamp, bot_id, False))
            continue
        m = _TRAVEL_RE.search(p.message)
        if m:
            travels.append((p.timestamp, m.group("bot_id"), float(m.group("buffer_ms"))))

    events: list[LiftEvent] = []
    for complete_ts, bot_id, is_maxdown_settle in completes:
        order_ts: datetime | None = None
        target_mm: float | None = None
        for ts, bid, target in reversed(orders):
            if bid != bot_id or ts > complete_ts:
                continue
            if (complete_ts - ts).total_seconds() <= _ORDER_LOOKBACK_SECONDS:
                order_ts, target_mm = ts, target
            break  # nearest preceding order for this bot, match or not

        anchor_ts = order_ts if order_ts is not None else complete_ts
        pre_height = _height_before(telemetry.get(bot_id, []), anchor_ts)

        # An EXPLICIT maxdown-settle order where the fork was already within
        # tolerance of the (bot-specific) maxdown height before the order
        # was even sent is a real no-op -- the fork never moved. Applying
        # telemetry/buffer-based correction here is actively misleading: a
        # "telemetry" crossing would just be the next periodic #recv sample
        # confirming a height the bot was ALREADY at (that sample can
        # legitimately arrive a long time after the order with no real
        # settling happening in between), and "estimated_buffer" would
        # invent a travel-time estimate for a move that never happened.
        # Confirmed real: task fc94362b-4546-427d-ac1d-291706f2fb93, bot
        # 208 -- a maxdown order to 260mm with pre-height already at 262mm
        # produced a spurious ~7.9s "estimated_buffer" overlap despite the
        # fork not actually needing to travel at all. Deliberately does
        # NOT apply to "during parallel navigation" completions (a real
        # functional lift mid-travel, never a settle, even if its target
        # happens to coincide with a maxdown value) -- see
        # _MAXDOWN_SETTLE_COMPLETE_RE.
        is_maxdown_noop = (
            is_maxdown_settle
            and pre_height is not None
            and target_mm is not None
            and abs(pre_height - target_mm) <= DEFAULT_TOLERANCE_MM
        )

        if is_maxdown_noop:
            corrected_at = None
            method = None
            max_buffer = None
        else:
            buffers = [
                buffer_ms
                for ts, bid, buffer_ms in travels
                if bid == bot_id
                and ts >= complete_ts
                and (ts - complete_ts).total_seconds() <= _TRAVEL_LOOKAHEAD_SECONDS
            ]
            max_buffer = max(buffers) if buffers else None

            telemetry_ts = None
            if target_mm is not None and order_ts is not None:
                telemetry_ts = find_telemetry_completion(telemetry.get(bot_id, []), order_ts, target_mm)

            if telemetry_ts is not None and telemetry_ts > complete_ts:
                corrected_at = telemetry_ts
                method = "telemetry"
            elif max_buffer:
                corrected_at = complete_ts + timedelta(milliseconds=max_buffer)
                method = "estimated_buffer"
            else:
                corrected_at = None
                method = None

        direction = classify_direction(pre_height, target_mm)
        coordinate = _xy_at_or_before(coordinates.get(bot_id, []), corrected_at or complete_ts)

        events.append(
            LiftEvent(
                bot_id=bot_id,
                order_sent_at=order_ts,
                logged_complete_at=complete_ts,
                target_height_mm=target_mm,
                corrected_complete_at=corrected_at,
                correction_method=method,
                buffer_ms=max_buffer,
                direction=direction,
                coordinate=coordinate,
            )
        )

    return events


# How long a plateau must hold before it counts as a real settled height
# rather than a transient sample mid-motion (confirmed against a real
# capture, task 70f0fa18...: real held states last several seconds; a
# ~0.05-0.3s "plateau" is just noise/an intermediate reading during a
# continuous physical rise, not somewhere the fork actually stopped).
_MIN_PLATEAU_HOLD_SECONDS = 1.0

# A fork-adjustment event within this many seconds of an existing LiftEvent's
# own (corrected or logged) completion is the SAME physical move already
# shown there -- dropped to avoid double-counting.
_FORK_ADJUSTMENT_DEDUP_WINDOW_SECONDS = 5.0


def _stable_plateaus(
    readings: list[tuple[datetime, float]], tolerance_mm: float = DEFAULT_TOLERANCE_MM
) -> list[tuple[datetime, datetime, float]]:
    """Groups consecutive readings into (start_ts, end_ts, height) runs
    where height stays within `tolerance_mm` of the run's own first
    reading -- collapses one continuous physical move's many samples down
    to a single before/after plateau pair."""
    if not readings:
        return []
    plateaus = []
    seg_start_ts, seg_start_h = readings[0]
    seg_end_ts = seg_start_ts
    for ts, h in readings[1:]:
        if abs(h - seg_start_h) <= tolerance_mm:
            seg_end_ts = ts
        else:
            plateaus.append((seg_start_ts, seg_end_ts, seg_start_h))
            seg_start_ts, seg_start_h, seg_end_ts = ts, h, ts
    plateaus.append((seg_start_ts, seg_end_ts, seg_start_h))
    return plateaus


def _merged_transitions(
    plateaus: list[tuple[datetime, datetime, float]]
) -> list[tuple[float, float, datetime, datetime]]:
    """(from_height, to_height, changed_at, started_at) for each real
    height change, with consecutive same-direction transitions merged into
    one (a fork settling briefly mid-rise before continuing shouldn't
    produce two separate "pick" events for what's really one continuous
    raise). `changed_at` is when the new height settled/held (the existing
    behavior); `started_at` is the earliest telemetry evidence the fork
    left `from_height` -- the very next plateau in the FULL (unfiltered)
    sequence, which may itself be a sub-1s noisy plateau filtered out of
    `significant` below, i.e. the first sample that already differs from
    the old held height. Confirmed real (task 6227a076..., bot 200): this
    is ~1.16s earlier than `changed_at` for the 262->478mm rise before the
    relay_storable drop, and lands within the *previous* movement phase's
    own window rather than after it.
    """
    indexed = list(enumerate(plateaus))
    significant = [(idx, p) for idx, p in indexed if (p[1] - p[0]).total_seconds() >= _MIN_PLATEAU_HOLD_SECONDS]
    if len(significant) < 2:
        return []

    transitions = []
    i = 0
    while i < len(significant) - 1:
        from_idx, from_p = significant[i]
        from_h = from_p[2]
        j = i + 1
        to_idx, to_p = significant[j]
        to_ts, to_h = to_p[0], to_p[2]
        direction = 1 if to_h > from_h else -1
        while j + 1 < len(significant):
            next_idx, next_p = significant[j + 1]
            next_h = next_p[2]
            next_direction = 1 if next_h > to_h else (-1 if next_h < to_h else 0)
            if next_direction != direction:
                break
            j += 1
            to_idx, to_p = significant[j]
            to_ts, to_h = to_p[0], to_p[2]
        started_at = plateaus[from_idx + 1][0] if from_idx + 1 < len(plateaus) else from_p[1]
        transitions.append((from_h, to_h, to_ts, started_at))
        i = j

    return transitions


def build_tote_transfer_events(lines: list[ParsedLine]) -> list[ForkAdjustmentEvent]:
    """Ground-truth pick/drop events from order+completion pairs -- HTM's
    `htm_load_tote`/`htm_unload_tote` (see the module-level docstring note
    above _TOTE_ORDER_RE) and VTM's `tote_load`/`tote_unload` (see the note
    above _VTM_TOTE_ORDER_RE). Both carry the real target height directly
    and have a genuine completion confirmation (not a premature-ack like
    simultaneousForkLift) -- the label ("pick"/"drop") comes straight from
    the action name, no nearest-waypoint guessing needed.

    The two bot types differ in how completion is matched: HTM's "Received
    X_finished for tote <<...>>" line carries the tote_id, so its
    completion is matched by (bot_id, action, tote_id) -- exact and
    unambiguous. VTM's actionStates FINISHED signal carries neither
    tote_id nor the order's own action string (see _VTM_ACTION_STATE_RE),
    so its completion is matched by nearest FOLLOWING FINISHED of the same
    action_type on the same bot instead -- safe because a VTM bot only
    ever runs one load/unload subtask at a time (confirmed structurally by
    the relay_group_task SubTask_list model), so "nearest following" can
    never cross into a different, unrelated transfer.

    `from_height_mm` is still taken from telemetry (the last reading before
    the order), same as build_lift_events' pre-order height lookup.
    """
    telemetry = parse_lift_telemetry(lines)
    coordinates = parse_agv_coordinates(lines)

    orders: list[tuple[datetime, str, str, float, str]] = []  # (ts, bot_id, action, height, tote_id)
    finishes: list[tuple[datetime, str, str, str]] = []  # (ts, bot_id, action, tote_id) -- HTM only
    vtm_finishes: dict[str, list[tuple[datetime, str]]] = {}  # bot_id -> [(ts, action_type), ...], sorted
    seen_vtm_tote_finished: set[tuple[str, str]] = set()  # (bot_id, action_uuid), dedupes repeated FINISHED sightings

    for p in lines:
        if p.function == _ORDER_FUNCTION:
            m = _TOTE_ORDER_RE.search(p.message)
            if m:
                orders.append(
                    (p.timestamp, m.group("bot_id"), m.group("action"), float(m.group("height")), m.group("tote_id"))
                )
                continue
            m = _VTM_TOTE_ORDER_RE.search(p.message)
            if m:
                orders.append(
                    (p.timestamp, m.group("bot_id"), m.group("action"), float(m.group("height")), m.group("tote_id"))
                )
            continue
        m = _TOTE_FINISHED_RE.search(p.message)
        if m:
            finishes.append((p.timestamp, m.group("bot_id"), m.group("action"), m.group("tote_id")))
            continue
        m = _VTM_ACTION_STATE_RE.search(p.message)
        if m and m.group("action_type") in ("toteLoad", "toteUnload") and m.group("status") == "FINISHED":
            key = (m.group("bot_id"), m.group("action_uuid"))
            if key not in seen_vtm_tote_finished:
                seen_vtm_tote_finished.add(key)
                vtm_finishes.setdefault(m.group("bot_id"), []).append((p.timestamp, m.group("action_type")))

    for bot_id in vtm_finishes:
        vtm_finishes[bot_id].sort(key=lambda pair: pair[0])

    def _vtm_action_type_for(action: str) -> str:
        return "toteLoad" if action == "tote_load" else "toteUnload"

    def _nearest_vtm_finish(bot_id: str, action: str, order_ts: datetime) -> datetime | None:
        action_type = _vtm_action_type_for(action)
        for ts, at in vtm_finishes.get(bot_id, []):
            if at != action_type or ts < order_ts:
                continue
            if (ts - order_ts).total_seconds() <= _TOTE_TRANSFER_LOOKAHEAD_SECONDS:
                return ts
            break  # sorted ascending -- first qualifying candidate is nearest, whether in-window or not
        return None

    events: list[ForkAdjustmentEvent] = []
    for order_ts, bot_id, action, height, tote_id in orders:
        if action in _VTM_TOTE_LABELS:
            finish_ts = _nearest_vtm_finish(bot_id, action, order_ts)
        else:
            match = next(
                (
                    f
                    for f in finishes
                    if f[1] == bot_id
                    and f[2] == action
                    and f[3] == tote_id
                    and f[0] >= order_ts
                    and (f[0] - order_ts).total_seconds() <= _TOTE_TRANSFER_LOOKAHEAD_SECONDS
                ),
                None,
            )
            finish_ts = match[0] if match else None
        if finish_ts is None:
            continue
        pre_height = _height_before(telemetry.get(bot_id, []), order_ts)
        coordinate = _xy_at_or_before(coordinates.get(bot_id, []), finish_ts)
        label = _TOTE_TRANSFER_LABELS.get(action) or _VTM_TOTE_LABELS[action]
        events.append(
            ForkAdjustmentEvent(
                bot_id=bot_id,
                timestamp=finish_ts,
                from_height_mm=pre_height if pre_height is not None else height,
                to_height_mm=height,
                direction=classify_direction(pre_height, height) or "down",
                label=label,
                started_at=order_ts,
                coordinate=coordinate,
            )
        )

    return events


def build_fork_adjustment_events(
    lines: list[ParsedLine], existing_lift_events: list[LiftEvent]
) -> list[ForkAdjustmentEvent]:
    """Fork height changes visible in the AGV's own telemetry that aren't
    already shown as a LiftEvent -- e.g. `set_fork_height_to_
    entry_height_without_tote`/`set_fork_height_to_htm_bot_for_pps`, which
    (unlike `simultaneousForkLift`) don't have a premature-completion
    problem to correct, just a real height change worth surfacing.
    `existing_lift_events` is used purely for dedup (see
    _FORK_ADJUSTMENT_DEDUP_WINDOW_SECONDS) -- this never re-derives or
    duplicates what build_lift_events already reports.

    Also includes ground-truth htm_load_tote/htm_unload_tote events (see
    build_tote_transfer_events) -- confirmed real (task 6227a076...) that
    the telemetry-plateau merge alone can silently absorb a real drop
    action into a longer surrounding descent (the drop's own intermediate
    height never held long enough to form its own plateau).

    Deduping a plateau transition against a tote-transfer event requires
    BOTH close timing AND a matching `to_height` (not just proximity in
    time) -- confirmed necessary against the same real trace: the prep-rise
    immediately before a drop (e.g. 262->478mm, arriving ~5s before the
    drop's own completion) is a *different*, still-worth-showing event from
    the drop itself (478->420mm) despite landing inside the dedup time
    window; matching height as well is what tells them apart. Dedup against
    existing_lift_events stays time-only (its target_height_mm already IS
    the plateau's own to_height in every real case seen, so height-matching
    there wouldn't change anything, only add complexity).
    """
    tote_transfer_events = build_tote_transfer_events(lines)

    telemetry = parse_lift_telemetry(lines)
    coordinates = parse_agv_coordinates(lines)
    covered_times = [le.corrected_complete_at or le.logged_complete_at for le in existing_lift_events]

    def _confirmed_by_tote_transfer(to_h: float, changed_at: datetime) -> bool:
        return any(
            abs((changed_at - e.timestamp).total_seconds()) <= _FORK_ADJUSTMENT_DEDUP_WINDOW_SECONDS
            and abs(to_h - e.to_height_mm) <= DEFAULT_TOLERANCE_MM
            for e in tote_transfer_events
        )

    events: list[ForkAdjustmentEvent] = list(tote_transfer_events)
    for bot_id, readings in telemetry.items():
        plateaus = _stable_plateaus(readings)
        for from_h, to_h, changed_at, started_at in _merged_transitions(plateaus):
            delta = to_h - from_h
            if abs(delta) < DEFAULT_TOLERANCE_MM:
                continue
            if any(
                abs((changed_at - ct).total_seconds()) <= _FORK_ADJUSTMENT_DEDUP_WINDOW_SECONDS
                for ct in covered_times
            ):
                continue
            if _confirmed_by_tote_transfer(to_h, changed_at):
                continue
            events.append(
                ForkAdjustmentEvent(
                    bot_id=bot_id,
                    timestamp=changed_at,
                    from_height_mm=from_h,
                    to_height_mm=to_h,
                    direction="up" if delta > 0 else "down",
                    started_at=started_at,
                    coordinate=_xy_at_or_before(coordinates.get(bot_id, []), changed_at),
                )
            )

    return sorted(events, key=lambda e: e.timestamp)
