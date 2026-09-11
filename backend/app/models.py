"""Core data model for parsed task lifecycles.

See PLAN.md "Core data model" - TaskEvent/TaskTrace here are the in-memory
representation; SQLAlchemy ORM models for persistence live at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase


class Confidence(str, Enum):
    """Whether an event's task attribution came directly from the log line
    (EXACT - the line itself carried MainTaskKey) or was inferred by the
    butler_id + time-window fallback heuristic (HEURISTIC) for task types
    that don't log MainTaskKey on movement lines. The UI must be able to
    show this distinction - see correlation.py.
    """

    EXACT = "exact"
    HEURISTIC = "heuristic"


class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


@dataclass
class TaskEvent:
    timestamp: datetime
    module: str
    function: str
    line_no: int
    raw_line: str
    phase_label: str | None = None
    attr_tag: str | None = None
    bot_id: str | None = None
    confidence: Confidence = Confidence.EXACT
    # The real (x, y) grid coordinate this movement arrived at, straight
    # from the goto_barcode_completed line itself (see task_types/*.py's
    # parse_movement) -- set ONLY for movement events, never for tracing
    # events. Exists because multiple physically distinct waypoints can
    # share the same attr_tag (confirmed real for VTM/relay_group_task:
    # e.g. {11,47}, {11,58}, {11,51}, {11,54} all tag as
    # ttp_storable_io_point), which otherwise makes every leg between them
    # collapse into an indistinguishable "ttp_storable_io_point ->
    # ttp_storable_io_point" phase with no way to tell which physical stop
    # was which.
    coordinate: tuple[int, int] | None = None


@dataclass
class LiftEvent:
    """A `simultaneousForkLift` order (blockingType=NONE -- see
    parsers/lift_events.py). The AGV acks this order, and the log records
    it "completed" the instant that ack arrives, NOT when the fork
    physically reaches height -- every other bot command blocks on real
    completion; this is the one exception. `logged_complete_at` is that
    premature timestamp; `corrected_complete_at` is the best estimate of
    when the fork actually got there, via one of two methods:

      - "telemetry": the AGV's own periodically-reported liftHeight crossed
        within tolerance of the commanded target, after the logged
        "completed" timestamp -- ground truth, and confirmed real (not
        just a theoretical fallback path) against an actual fork
        descending through several intermediate heights before settling.
      - "estimated_buffer": no *post*-completion-flag telemetry crossing
        was found -- either the AGV's telemetry doesn't reflect the lift
        dynamically, or (equally common) the fork was already within
        tolerance before the order was even sent, so there's no later
        crossing to observe. Either way, the logged timestamp plus the
        system's own computed `finaltime_with_buffer` travel-time estimate
        is used instead, and callers/UI should visibly label this as an
        estimate, not ground truth. `correction_method` is None if neither
        signal was available.

    Always Confidence.HEURISTIC: these lines don't restate the task's own
    id/MainTaskKey at all (see lift_events.py), so attribution is by
    butler_id + falling inside the task's own time window, same idea as
    parsers/correlation.py uses for orphan movement events.

    `direction` ("up"/"down"/None) is derived by comparing the AGV's own
    reported liftHeight immediately *before* this order was sent against
    `target_height_mm` -- confirmed against a real pickup/drop cycle
    (task 70f0fa18...): fork height went 252mm (idle/maxdown) -> ~478mm
    (raised to entry height for pickup) -> 252mm (this event, DOWN, right
    after the tote was loaded) -> ~548mm (raised again for the PPS
    handoff) -> 252mm (this event, DOWN, right after the PPS drop). None
    means no significant pre-order height change was observed (e.g. the
    fork was already essentially at the target -- a same-height
    confirmation, not a real move).

    `context_label` is set by parsers/event_context.py, using the nearest
    real movement phase's `to_attr` (e.g. "lift down @ relay_storable") --
    deliberately not a fabricated domain term, since it's just naming the
    waypoint the trace itself already observed.

    `coordinate` is the AGV's own (x, y) from the same agvPosition
    telemetry reading nearest this event's completion -- same source line
    as target_height_mm/direction, just reading a different field.
    """

    bot_id: str
    order_sent_at: datetime | None
    logged_complete_at: datetime
    target_height_mm: float | None
    corrected_complete_at: datetime | None
    correction_method: Literal["telemetry", "estimated_buffer"] | None
    buffer_ms: float | None
    confidence: Confidence = Confidence.HEURISTIC
    direction: Literal["up", "down"] | None = None
    context_label: str | None = None
    coordinate: tuple[float, float] | None = None

    @property
    def understated_by_seconds(self) -> float | None:
        if self.corrected_complete_at is None:
            return None
        return (self.corrected_complete_at - self.logged_complete_at).total_seconds()


@dataclass
class ForkAdjustmentEvent:
    """A fork height change detected directly from the AGV's own liftHeight
    telemetry that is NOT already captured as a LiftEvent -- e.g.
    `set_fork_height_to_entry_height_without_tote` (raising to approach a
    tote before pickup) or `set_fork_height_to_htm_bot_for_pps` (raising
    for the PPS handoff). Unlike `simultaneousForkLift` (blockingType=NONE,
    the one command with a premature-completion problem to correct), these
    subtasks don't need timing correction -- there's no order/logged-
    complete pair to reconcile, just a real height change worth surfacing
    on its own. See parsers/lift_events.py's build_fork_adjustment_events
    for the plateau-detection this is built from and how it avoids
    double-counting a change already shown as a LiftEvent.

    `label` is "pick"/"drop" specifically when the nearest movement phase
    is `relay_storable` itself (the user's own vocabulary for the load/
    unload action there); "lift up"/"lift down" elsewhere (e.g.
    approaching a PPS handoff) -- set by parsers/event_context.py, which
    has the trace's own phases this module doesn't see.

    `started_at` is the earliest telemetry evidence the fork left
    `from_height_mm` -- for a plateau-derived event, the first reading that
    differs from the old held height (which may itself be too short-lived
    to form its own plateau); for a tote-transfer event, the order's own
    send instant. `timestamp` stays the settle/completion instant it always
    was; `started_at` exists so callers can show that a rise can genuinely
    begin *during* the tail of the previous movement phase rather than only
    after it -- confirmed real (task 6227a076...): the fork was already
    seen moving off 262mm at 06:41:33.619, one second before the
    highway -> relay_storable_io_point phase itself finished arriving
    (06:41:33.638), which `timestamp` alone (06:41:34.784, when it settled
    at the new height) would have hidden entirely.

    `coordinate` is the AGV's own (x, y) at `timestamp`, same telemetry
    reading the height came from.

    Always Confidence.HEURISTIC: these #recv lines never restate a task_id.
    """

    bot_id: str
    timestamp: datetime
    from_height_mm: float
    to_height_mm: float
    direction: Literal["up", "down"]
    confidence: Confidence = Confidence.HEURISTIC
    label: str | None = None
    started_at: datetime | None = None
    coordinate: tuple[float, float] | None = None


@dataclass
class RotationEvent:
    """An in-place turn, from one of two sources -- see parsers/
    rotation_events.py for both reconstructions in full:

      - "telemetry" (ground truth): the AGV's own reported heading
        (`agvPosition.theta` in its VDA5050 state stream) genuinely
        stepping between quantized values (0, +-pi/2, pi) -- confirmed
        real against task ef3d2ee1..., including a rotation on the
        highway -> relay_storable_io_point leg that the estimate below
        alone would have under-counted. `coordinate` comes from the same
        #recv reading's agvPosition.x/y (same source line lift_events.py
        reads liftHeight from).
      - "planned_path_estimate": the `turn_step` reconstruction from a
        navigator_agent planned-path dump (see module docstring for the
        tuple decode and the re-plan-dedup/timestamp-precision caveats).
        Has a `coordinate` from the planned grid step itself, used only as
        a fallback where no matching telemetry-confirmed rotation was
        found nearby (see build_rotation_events's dedup step, which drops
        planned-path estimates telemetry has already confirmed, to avoid
        double-counting the same physical turn twice).

    Always Confidence.HEURISTIC for the same reason as LiftEvent: neither
    source restates a task_id.

    `significance` (set by parsers/event_context.py) is "major" when this
    rotation lands within a few seconds of the bot arriving at OR
    departing a key waypoint (relay_storable_io_point / pps /
    pps_entry_queue) -- both "the bot reaches the io point, then rotates"
    AND "the bot just left pps, rotates before heading down the highway"
    count -- and "minor" for everything else (ordinary in-transit turns at
    highway intersections). Only major rotations are worth calling out
    individually; minor ones are meant to be aggregated into a single
    count instead. `context_label` (e.g. "pps exit", "arrival @
    relay_storable_io_point") is the human-readable reason it was major;
    None for minor rotations.
    """

    bot_id: str
    timestamp: datetime
    coordinate: tuple[float, float] | None
    duration_ms: float
    confidence: Confidence = Confidence.HEURISTIC
    significance: Literal["major", "minor"] = "minor"
    method: Literal["telemetry", "planned_path_estimate"] = "planned_path_estimate"
    context_label: str | None = None

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000.0


# A graceful-stop/api_stop ack this many seconds or less before
# charging_complete counts as having triggered it -- confirmed real
# across two independently-found traces: task 87e760ef... (9.2s gap) and
# task 16efa65e... (3.4s gap). Generous margin above both without being
# wide enough to falsely associate an unrelated, much-earlier graceful
# stop with a later, actually-natural completion.
_GRACEFUL_STOP_TO_COMPLETE_TOLERANCE_SECONDS = 30.0


@dataclass
class ChargeTiming:
    """Charge-cycle timing breakdown for chargetask -- see
    parsers/charge_timing.py for the full real-trace-derived milestone
    sequence this is built from. None for every non-chargetask trace.
    """

    assigned_at: datetime | None = None
    reached_charger_reinit_at: datetime | None = None
    reached_charger_at: datetime | None = None
    charging_started_at: datetime | None = None
    charging_complete_at: datetime | None = None
    return_dispatched_at: datetime | None = None
    return_reached_charger_reinit_at: datetime | None = None
    parked_at: datetime | None = None
    # Battery level (0-100%) from the AGV's own telemetry (batteryState.
    # batteryCharge, same #recv source lift/rotation telemetry reads --
    # see lift_events.py's parse_battery_telemetry), nearest each
    # milestone instant. Confirmed real (task
    # 87e760ef-1639-4b02-9c06-7efcefc8148d, bot 210): 57.0% at
    # reached_charger_at, 70.0% at charging_complete_at -- a real,
    # meaningful rise over the cycle. None if no reading fell within
    # lift_events.py's lookup tolerance of the milestone (e.g. the bot's
    # own telemetry gap, or this trace predates battery-level tracking).
    battery_pct_at_charger_arrival: float | None = None
    battery_pct_at_charging_complete: float | None = None
    # An API-issued graceful stop (see charge_timing.py's
    # _GRACEFUL_STOP_RE) -- confirmed real across 2 independently-found
    # traces (task 87e760ef..., task 16efa65e...) that this is what
    # actually TRIGGERS charging_complete (firing only ~3-4s later in
    # both), not an unrelated event. None means charging ended without
    # ever receiving this ack in the task's own log window (e.g. it
    # completed by reaching a full charge on its own).
    graceful_stop_at: datetime | None = None
    graceful_stop_reason: str | None = None

    @property
    def charging_stopped_via_api(self) -> bool:
        """True when an API-issued graceful stop preceded charging_complete
        closely enough (see _GRACEFUL_STOP_TO_COMPLETE_TOLERANCE_SECONDS)
        to plausibly be what ended it, rather than charging reaching
        completion on its own and a graceful stop merely happening to be
        logged somewhere else in this task's wider window."""
        if self.graceful_stop_at is None or self.charging_complete_at is None:
            return False
        return (
            0
            <= (self.charging_complete_at - self.graceful_stop_at).total_seconds()
            <= _GRACEFUL_STOP_TO_COMPLETE_TOLERANCE_SECONDS
        )

    @property
    def assigned_to_reinit_seconds(self) -> float | None:
        if self.assigned_at is None or self.reached_charger_reinit_at is None:
            return None
        return (self.reached_charger_reinit_at - self.assigned_at).total_seconds()

    @property
    def reinit_to_charger_seconds(self) -> float | None:
        if self.reached_charger_reinit_at is None or self.reached_charger_at is None:
            return None
        return (self.reached_charger_at - self.reached_charger_reinit_at).total_seconds()

    @property
    def docked_to_charging_started_seconds(self) -> float | None:
        """The specific gap the user asked to have clarified: is there a
        real wait between reaching the charger (docked) and the charge
        actually starting, or does charging begin (near-)instantly on
        arrival? Confirmed real (task 87e760ef...): reached_charger_at and
        charging_started_at landed only 16ms apart -- i.e. charging began
        essentially the instant the bot docked, no separate "waiting to
        start" phase observed in that trace. Surfaced as its own number
        rather than left implicit so this doesn't have to be inferred by
        eyeballing two nearly-identical timestamps."""
        if self.reached_charger_at is None or self.charging_started_at is None:
            return None
        return (self.charging_started_at - self.reached_charger_at).total_seconds()

    @property
    def outbound_travel_seconds(self) -> float | None:
        if self.assigned_at is None or self.reached_charger_at is None:
            return None
        return (self.reached_charger_at - self.assigned_at).total_seconds()

    @property
    def charging_duration_seconds(self) -> float | None:
        if self.charging_started_at is None or self.charging_complete_at is None:
            return None
        return (self.charging_complete_at - self.charging_started_at).total_seconds()

    @property
    def charging_stop_to_reinit_seconds(self) -> float | None:
        """The specific sub-leg the user asked to see split out: how long
        it takes to back out of the charger dock to the reinit/staging
        point, as its own number rather than lumped into the whole return
        leg."""
        if self.charging_complete_at is None or self.return_reached_charger_reinit_at is None:
            return None
        return (self.return_reached_charger_reinit_at - self.charging_complete_at).total_seconds()

    @property
    def reinit_to_parked_seconds(self) -> float | None:
        if self.return_reached_charger_reinit_at is None or self.parked_at is None:
            return None
        return (self.parked_at - self.return_reached_charger_reinit_at).total_seconds()

    @property
    def return_travel_seconds(self) -> float | None:
        if self.charging_complete_at is None or self.parked_at is None:
            return None
        return (self.parked_at - self.charging_complete_at).total_seconds()

    @property
    def total_seconds(self) -> float | None:
        if self.assigned_at is None or self.parked_at is None:
            return None
        return (self.parked_at - self.assigned_at).total_seconds()


@dataclass
class TaskTrace:
    request_id: str | None
    task_id: str | None
    task_type: str | None
    butler_id: str | None
    events: list[TaskEvent] = field(default_factory=list)
    lift_events: list[LiftEvent] = field(default_factory=list)
    rotation_events: list[RotationEvent] = field(default_factory=list)
    fork_adjustment_events: list[ForkAdjustmentEvent] = field(default_factory=list)
    status: TaskStatus = TaskStatus.INCOMPLETE
    created_at: datetime | None = None
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
    tote_ids: list[str] = field(default_factory=list)
    warning_lines: list[str] = field(default_factory=list)
    charge_timing: ChargeTiming | None = None

    @property
    def total_duration_seconds(self) -> float | None:
        if self.created_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.created_at).total_seconds()

    @property
    def cycle_duration_seconds(self) -> float | None:
        """Full cycle time from task assignment to completion.
        `dispatched_at` (set once the bot's SubTask_list is computed --
        confirmed to land within ~100ms of the earlier "Starting TaskId:"
        line on a real trace) is the reliable stand-in for "assigned to a
        bot" -- unlike total_duration_seconds, this doesn't depend on the
        "#Task created" marker, which not every task type/instance logs
        (confirmed against a real, cleanly-completed relay_pps_task that
        never logged it, leaving created_at blank despite finishing fine).
        """
        if self.dispatched_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.dispatched_at).total_seconds()

    @property
    def has_warnings_or_errors(self) -> bool:
        return len(self.warning_lines) > 0

    @property
    def queued_duration_seconds(self) -> float | None:
        if self.created_at is None or self.dispatched_at is None:
            return None
        return (self.dispatched_at - self.created_at).total_seconds()

    def phase_durations(self) -> list[dict]:
        """One entry per MOVEMENT event (attr_tag set), giving the duration
        since the previous movement event. Non-movement events in between
        (fork height changes, tote load, pps_control - attr_tag is None)
        are intentionally skipped as `from`/`to` endpoints here: they're
        instantaneous actions, not a distinct physical location, so a
        "phase" is always attributed to the last known grid attribute, not
        to whichever event happens to sit immediately before it in the
        list. This mirrors the manual analysis done this session, where
        e.g. "relay_storable_io_point -> relay_storable" is one phase
        regardless of any tracing lines logged in between.
        """
        out = []
        prev: TaskEvent | None = None
        for ev in self.events:
            if ev.attr_tag is None:
                continue
            if prev is not None:
                out.append(
                    {
                        "from_attr": prev.attr_tag,
                        "to_attr": ev.attr_tag,
                        "phase_label": ev.phase_label,
                        "duration_seconds": (ev.timestamp - prev.timestamp).total_seconds(),
                        "confidence": ev.confidence.value,
                        "timestamp": ev.timestamp,
                        # Real (x, y) at each end -- lets a caller (see
                        # frontend TaskSwimlane.tsx) distinguish two phases
                        # that share the same attr_tag but are actually
                        # different physical stops (confirmed real for
                        # VTM: several distinct coordinates all tag as
                        # ttp_storable_io_point).
                        "from_coordinate": prev.coordinate,
                        "to_coordinate": ev.coordinate,
                    }
                )
            prev = ev
        return out


class Base(DeclarativeBase):
    pass


class TaskTraceRow(Base):
    """Persisted TaskTrace cache -- see PLAN.md 'Persistence/caching' and
    api/routes.py's cache-hit/write-through logic.

    Deliberately caches the RAW grepped log lines (task_lines_json plus the
    separate lift_lines_json/rotation_lines_json -- one column per distinct
    SSH grep the live path already makes, so a cache hit re-derives a trace
    by calling the exact same parsing functions with the exact same inputs,
    never a separate/duplicated code path), not the already-built
    LiftEvent/RotationEvent/etc. objects. That means a cache hit still runs
    today's parsing logic fresh every time -- a parser bug fix (this
    session had several) is picked up immediately for every cached task
    too, rather than serving a stale, already-wrong result forever.

    Only ever written for a trace whose status is COMPLETED or FAILED --
    logs are append-only, so a terminal task's own lines can never change,
    and a cache hit is valid indefinitely (no TTL needed, see routes.py).
    A RUNNING/INCOMPLETE trace is never cached, since its own lines could
    still be arriving.
    """

    __tablename__ = "task_traces"

    task_id = Column(String, primary_key=True)
    request_id = Column(String, index=True, nullable=True)
    butler_ip = Column(String, index=True, nullable=False)
    task_type = Column(String, index=True, nullable=True)
    butler_id = Column(String, index=True, nullable=True)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_duration_seconds = Column(Float, nullable=True)
    task_lines_json = Column(JSON, nullable=False)  # raw lines from the main task_id grep
    lift_lines_json = Column(JSON, nullable=True)  # raw lines from grep_bot_lift_lines, if the window enrichment ran
    rotation_lines_json = Column(JSON, nullable=True)  # raw lines from grep_bot_rotation_lines, same condition
    fetched_at = Column(DateTime, nullable=False)  # when this row was last (re)written


class ScanJobRow(Base):
    __tablename__ = "scan_jobs"

    job_id = Column(String, primary_key=True)
    butler_ip = Column(String, nullable=False)
    mode = Column(String, nullable=False)  # "task" | "window" | "scan"
    params_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False)  # "queued" | "running" | "done" | "error"
    result_json = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)


class BenchmarkResultRow(Base):
    """A user-saved snapshot of one task's benchmark-vs-manual-threshold
    check (see frontend TaskSwimlane.tsx's pass/fail badges and
    lib/baselines.ts) -- written only when the user explicitly clicks
    "Save benchmark result", never automatically on every page view.
    task_id is NOT the primary key: the same task can be saved more than
    once (e.g. after adjusting thresholds), so history accumulates as
    separate rows, newest first via `recorded_at` -- see
    GET /api/benchmark-result/{task_id}, itself only ever called when the
    user explicitly asks to view saved results for a task.

    `thresholds_json` freezes the exact thresholds in effect at save time,
    since the user's live thresholds (browser-local, see lib/baselines.ts)
    can change later -- a saved pass/fail result must stay interpretable
    against what it was actually judged by, not whatever the threshold
    happens to be when someone looks at the history later.
    """

    __tablename__ = "benchmark_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, index=True, nullable=False)
    task_type = Column(String, nullable=True)
    butler_ip = Column(String, nullable=True)
    recorded_at = Column(DateTime, nullable=False)
    thresholds_json = Column(JSON, nullable=False)  # {liftMaxSeconds, rotationMaxSeconds, forkMaxSeconds}
    results_json = Column(JSON, nullable=False)  # list of per-sub-event {kind, label, duration_seconds, ...}
    pass_count = Column(Integer, nullable=False)
    fail_count = Column(Integer, nullable=False)
