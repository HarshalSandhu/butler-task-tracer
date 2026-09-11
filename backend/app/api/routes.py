"""HTTP API surface - see PLAN.md "Two operating modes + a bounded third".

Note what is NOT here: there is no endpoint, field, or model anywhere in
this module that accepts a private key, passphrase, or any credential
beyond `butler_ip`/`ssh_user`. See app/ssh/executor.py's module docstring
for the invariant this enforces.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models import BenchmarkResultRow, TaskStatus, TaskTraceRow
from app.parsers.aggregate_stats import TaskWindow, compute_lift_rotation_aggregates
from app.parsers.charge_timing import attach_battery_levels, build_charge_timing
from app.parsers.event_context import annotate_event_context
from app.parsers.generic_movement import build_generic_movement_events, extract_waypoint_labels
from app.parsers.id_resolver import find_request_id, resolve_task_id_from_request_id
from app.parsers.lift_events import build_fork_adjustment_events, build_lift_events, parse_battery_telemetry
from app.parsers.line_parser import parse_line, parse_lines
from app.parsers.rotation_events import build_rotation_events
from app.parsers.task_summary import (
    TASK_SUMMARY_GREP_PATTERN,
    TASK_SUMMARY_TYPES,
    build_task_summaries,
)
from app.parsers.terminal_state import _RELAY_GROUP_COMPLETE_RE, classify
from app.parsers.trace_builder import build_trace
from app.ssh.executor import (
    SshCommandError,
    SshTarget,
    check_connectivity,
    grep_bot_lift_lines,
    grep_bot_rotation_lines,
    grep_logs,
    list_debug_log_files,
    list_debug_log_files_with_mtime,
)

router = APIRouter()

MAX_SCAN_LOOKBACK_DAYS = 30
DEFAULT_SCAN_LOOKBACK_HOURS = 24

# Every task type restates its own type inline wherever it appears, e.g.
# `Task={relay_group_task,<<"KEY">>}` or `TaskId: {relay_pps_task,<<"KEY">>}`
# -- so the type can be read directly off the grepped lines for *any* task
# type, not just the ones with a registered resolver module. This is what
# lets a direct task_id search (no request_id) still pick the right
# resolver instead of defaulting to relay_pps_task and silently matching
# nothing.
def _sniff_task_type(lines: list[str], task_id: str) -> str | None:
    # Built via concatenation, not str.format() -- the pattern's own regex
    # braces (`\{...\}`) would otherwise collide with format()'s `{}` field
    # syntax (confirmed: this literally raised "unexpected '{' in field
    # name" against a real request).
    pattern = re.compile(r'\{(?P<task_type>\w+),<<"' + re.escape(task_id) + r'">>\}')
    for line in lines:
        m = pattern.search(line)
        if m:
            return m.group("task_type")
    return None


# Padding around the task's own observed time span before scoping the
# butler_id-wide lift-line/rotation-line greps to it -- see lift_events.py
# and rotation_events.py: neither of these lines restate a task_id, so this
# window is the only thing keeping an event from an unrelated, later task
# on the same bot from being misattributed here.
#
# Two tiers: when both created_at/completed_at are known (a cleanly
# classified trace - see terminal_state.py), those are real, tight task
# boundaries, so only a small pad is needed to catch an order/completion
# pair that straddles the edge. Confirmed against a real trace (task
# 70f0fa18...) that the old, single 120s pad on the *first/last observed
# event* (not the task's own start/end) reached past the task's real
# boundary and pulled in 2 of 5 lift events and 2 of 4 rotation events that
# actually belonged to a different task on the same bot. Falls back to the
# old generous pad only when completed_at isn't known (task still running,
# failed, or otherwise not cleanly bounded).
_TIGHT_WINDOW_PAD_SECONDS = 15
_BOT_EVENT_WINDOW_PAD_SECONDS = 120


def _task_time_window(trace) -> tuple[datetime, datetime] | None:
    if trace.completed_at is not None:
        # created_at needs the "#Task created" marker specifically, which
        # not every relay_pps_task logs (confirmed against a real trace,
        # 70f0fa18..., that completed cleanly but never logged that exact
        # marker) -- the earliest observed movement/tracing event is a
        # perfectly good stand-in start boundary when it's missing, still
        # far tighter than the loose fallback below.
        start = trace.created_at
        if start is None and trace.events:
            start = min(e.timestamp for e in trace.events)
        if start is not None:
            pad = timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS)
            return start - pad, trace.completed_at + pad

    timestamps = [e.timestamp for e in trace.events]
    for extra in (trace.created_at, trace.dispatched_at, trace.completed_at):
        if extra is not None:
            timestamps.append(extra)
    if not timestamps:
        return None
    pad = timedelta(seconds=_BOT_EVENT_WINDOW_PAD_SECONDS)
    return min(timestamps) - pad, max(timestamps) + pad


def _candidate_log_files(target: "SshTarget", window_start: datetime) -> list[str]:
    """A rotated file's mtime is ~when it stopped being written -- safe to
    skip anything that stopped before our window even starts. This is what
    makes a `butler_id=<N>` grep (common, unlike a task_id) tractable
    (confirmed against the real validation VM: unfiltered, it timed out
    past 180s scanning 12 files, ~500MB each).
    """
    files_with_mtime = list_debug_log_files_with_mtime(target)
    return [f for f, mtime in files_with_mtime if mtime >= window_start]


def _fetch_raw_lift_lines(target: "SshTarget", trace, candidate_files: list[str]) -> tuple[list[str], bool]:
    """Best-effort for the LIVE response: on an SshCommandError, returns
    ([], False) rather than raising, since the primary trace is already
    valid without this enrichment -- the whole task lookup shouldn't 502
    just because this one grep hiccuped. The `False` is what matters for
    caching (see _maybe_cache_trace): confirmed real (task
    b55bbb47-6d71-4222-9085-d3e1006042ac, bot 209) that a transient SSH
    failure here used to get cached as "this task genuinely has zero lift/
    rotation events" -- indistinguishable from a real empty result once
    swallowed to `[]` -- permanently hiding real data (a fresh grep for the
    same bot/window found 20000+ matching lines) behind a cache hit that
    never retried. (not trace.butler_id or not candidate_files) is True
    is NOT a failure -- there's genuinely nothing to fetch.
    """
    if not trace.butler_id or not candidate_files:
        return [], True
    try:
        return grep_bot_lift_lines(target, trace.butler_id, candidate_files), True
    except SshCommandError:
        return [], False


def _fetch_raw_rotation_lines(target: "SshTarget", trace, candidate_files: list[str]) -> tuple[list[str], bool]:
    if not trace.butler_id or not candidate_files:
        return [], True
    try:
        return grep_bot_rotation_lines(target, trace.butler_id, candidate_files), True
    except SshCommandError:
        return [], False


def _apply_lift_rotation_lines(
    trace, task_lines: list[str], raw_lift_lines: list[str], raw_rotation_lines: list[str]
) -> None:
    """Mutates trace.events/lift_events/fork_adjustment_events/
    rotation_events (and annotates their context) from already-fetched raw
    lines -- shared by the live SSH path and the cache-rebuild path below,
    so a cache hit runs the EXACT same parsing logic as a live fetch, just
    from a different line source, and can never silently drift from it.

    window is recomputed from `trace` itself rather than passed in, since
    it's a pure function of the trace's own timestamps (see
    _task_time_window) -- deterministically identical whether `trace` was
    just built live or rebuilt from cached raw lines.

    Generic movement-event recovery (see parsers/generic_movement.py) runs
    first, and only when trace.phase_durations() is still empty at this
    point -- i.e. the task type's own EXACT movement resolver
    (task_types/*.py) found nothing at all. Must happen before
    annotate_event_context below, so lift/rotation context-labeling
    (nearest_phase_attr) sees the recovered phases, not an empty list.

    For a chargetask, also attaches battery level at charger-arrival/
    charging-complete (see charge_timing.py's attach_battery_levels) --
    reuses these SAME already-fetched lift-marker lines (they carry
    batteryState.batteryCharge in the same #recv payload liftHeight comes
    from), no extra SSH round trip.
    """
    window = _task_time_window(trace)
    if window is None:
        return
    window_start, window_end = window

    if not trace.phase_durations() and trace.butler_id:
        waypoint_labels = extract_waypoint_labels(task_lines)
        if waypoint_labels:
            parsed_nav = [p for p in parse_lines(raw_rotation_lines) if window_start <= p.timestamp <= window_end]
            new_events = build_generic_movement_events(parsed_nav, waypoint_labels)
            if new_events:
                trace.events = sorted(trace.events + new_events, key=lambda e: e.timestamp)

    parsed_lift = [p for p in parse_lines(raw_lift_lines) if window_start <= p.timestamp <= window_end]
    trace.lift_events = build_lift_events(parsed_lift)
    trace.fork_adjustment_events = build_fork_adjustment_events(parsed_lift, trace.lift_events)
    parsed_rotation = [p for p in parse_lines(raw_rotation_lines) if window_start <= p.timestamp <= window_end]
    trace.rotation_events = build_rotation_events(parsed_rotation)
    annotate_event_context(trace)

    if trace.charge_timing is not None and trace.butler_id:
        battery_telemetry = parse_battery_telemetry(parsed_lift)
        attach_battery_levels(trace.charge_timing, battery_telemetry.get(trace.butler_id, []))


def _maybe_reclassify_relay_group_completion(trace, raw_lift_lines: list[str]) -> None:
    """relay_group_task's own completion marker ("The Current SubTask is :
    {subtask,set_relay_group_task_status,set_relay_group_task_status,
    [complete]}") never restates the task_id (see terminal_state.py's own
    module docstring) -- terminal_state.classify() only ever sees whatever
    build_trace() was given, which is the task_id-scoped grep, so in
    production it can NEVER actually observe this line, despite its own
    regex matching correctly in isolation (see test_terminal_state.py's
    synthetic-message test). Confirmed real (task 4e20786c...): a
    genuinely-completed VTM relay_group_task was reported INCOMPLETE,
    which then widened its lift/rotation window to the loose 120s fallback
    (see _task_time_window) and pulled in a DIFFERENT, adjacent task's own
    lift event -- directly corrupting the very lift-timing this fix exists
    to report accurately.

    raw_lift_lines already carries these lines (see executor.py's
    _LIFT_MARKER_PATTERN) as a side effect of the SAME butler_id-scoped
    fetch _fetch_raw_lift_lines already makes -- no extra SSH round trip.
    Only runs when still INCOMPLETE (never overrides an already-classified
    completed/failed trace) and only for relay_group_task (the one type
    missing this signal from its own grep).

    raw_lift_lines comes from the LOOSE fallback window (this function's
    whole reason for existing is that completed_at isn't known yet), which
    can span far enough to also catch the PRECEDING relay_group_task's own
    completion on the same bot -- confirmed real (task 4e20786c..., bot
    214): the fixture's window also contains a completion line at
    14:33:49.348, over a minute before this task even started. Only a
    match at/after `trace.dispatched_at` can be this task's own; anything
    earlier belongs to whatever ran before it.
    """
    if trace.status != TaskStatus.INCOMPLETE or trace.task_type != "relay_group_task":
        return
    parsed = list(parse_lines(raw_lift_lines))
    if trace.dispatched_at is not None:
        parsed = [p for p in parsed if p.timestamp >= trace.dispatched_at]
    if classify([p.message for p in parsed], task_id=trace.task_id) != TaskStatus.COMPLETED:
        return
    for p in parsed:
        if _RELAY_GROUP_COMPLETE_RE.search(p.message):
            trace.status = TaskStatus.COMPLETED
            trace.completed_at = p.timestamp
            return


def _build_trace(task_id: str, task_type: str | None, request_id: str | None, task_lines: list[str]):
    """The task_lines -> TaskTrace step shared by the live path and the
    cache-rebuild path -- everything downstream of "we have the raw
    task_id-grep lines", before the (separate) lift/rotation enrichment.
    """
    trace = build_trace(task_id=task_id, task_type=task_type, request_id=request_id, raw_lines=task_lines)
    if task_type == "chargetask":
        trace.charge_timing = build_charge_timing(list(parse_lines(task_lines)))
        # terminal_state.classify() doesn't know chargetask's own
        # completion markers (a different lifecycle than the relay
        # types' success/failure lines) -- charge_timing.parked_at is a
        # more precise, real signal that the full cycle (charge +
        # return) finished, and setting completed_at from it is what
        # lets _task_time_window's tight pad (rather than the loose
        # 120s fallback) apply to this task's rotation-event window too.
        if trace.charge_timing.parked_at is not None:
            trace.completed_at = trace.charge_timing.parked_at
            trace.status = TaskStatus.COMPLETED
    return trace


def _resolve_task_lines_and_trace(target: "SshTarget", req: "TaskLookupRequest"):
    """Live (uncached) task_id/request_id resolution + trace build -- the
    same steps get_task_trace's own live path performs, extracted as a
    standalone helper for get_task_full_logs's cache-miss fallback so it
    doesn't need a real trace's own butler_id/window without duplicating
    get_task_trace itself (which stays untouched -- its own inline version
    of this logic is left as-is to avoid any risk to that already-proven,
    cache-writing path).
    """
    log_files = list_debug_log_files(target)
    if not log_files:
        raise HTTPException(404, f"No debug.log files found on {req.butler_ip}")

    if req.task_id:
        search_id = req.task_id
    else:
        req_id_lines = grep_logs(target, req.request_id, log_files)
        resolved = resolve_task_id_from_request_id(req.request_id, req_id_lines)
        if resolved is None:
            raise HTTPException(
                404,
                f"request_id {req.request_id} found but no task_id resolved yet "
                "(task creation may not have completed, or logs have rotated past it)",
            )
        search_id = resolved.task_id

    task_lines = grep_logs(target, search_id, log_files)
    if not task_lines:
        raise HTTPException(404, f"No log lines found for task_id {search_id}")

    request_id_found = find_request_id(task_lines) or req.request_id
    task_type = _sniff_task_type(task_lines, search_id) or "relay_pps_task"
    if request_id_found:
        resolved = resolve_task_id_from_request_id(request_id_found, task_lines)
        if resolved:
            task_type = resolved.task_type

    trace = _build_trace(search_id, task_type, request_id_found, task_lines)
    return trace, task_lines


def _filter_lines_to_window(lines: list[str], window_start: datetime, window_end: datetime) -> list[str]:
    """Keeps only lines whose own timestamp falls in [window_start,
    window_end] -- candidate_files is already narrowed by FILE mtime (see
    _candidate_log_files), but a single file routinely spans well past one
    task's own window (the same bot's next several tasks), so this is a
    second, per-line pass. A line that doesn't match the lager format at
    all (e.g. a multi-line ~p dump continuation) has no timestamp of its
    own to check -- it's kept iff the entry it continues was kept, since
    it's genuinely part of that same log entry, not a separate one.
    """
    result: list[str] = []
    keep = False
    for raw in lines:
        parsed = parse_line(raw)
        if parsed is not None:
            keep = window_start <= parsed.timestamp <= window_end
        if keep:
            result.append(raw)
    return result


def _load_cached_trace_object(butler_ip: str, task_id: str):
    """Same cache-hit rebuild as _load_cached_trace, but returns the live
    TaskTrace object instead of its serialized dict -- for callers (like
    get_task_full_logs) that need trace.butler_id/_task_time_window(trace)
    rather than the API response shape. Returns None on a miss, meaning
    "no cached row" OR "cached row is for a different butler_ip" (task_id
    is the primary key, but two different boxes producing the same id
    would be a real bug worth falling through to a live fetch for, not
    silently serving the wrong box's data).
    """
    with SessionLocal() as session:
        row = session.get(TaskTraceRow, task_id)
    if row is None or row.butler_ip != butler_ip:
        return None
    trace = _build_trace(row.task_id, row.task_type, row.request_id, row.task_lines_json)
    _apply_lift_rotation_lines(trace, row.task_lines_json, row.lift_lines_json or [], row.rotation_lines_json or [])
    return trace


def _load_cached_trace(butler_ip: str, task_id: str) -> dict | None:
    """A cache hit rebuilds the trace fresh from the cached raw lines (see
    TaskTraceRow's docstring for why) -- returns None on a miss (see
    _load_cached_trace_object).
    """
    trace = _load_cached_trace_object(butler_ip, task_id)
    if trace is None:
        return None
    return _trace_to_dict(trace)


def _maybe_cache_trace(
    butler_ip: str,
    task_id: str,
    request_id: str | None,
    task_type: str | None,
    trace,
    task_lines: list[str],
    raw_lift_lines: list[str],
    raw_rotation_lines: list[str],
) -> None:
    """Write-through cache: only for a trace that reached a TERMINAL status
    (completed/failed). Logs are append-only, so a terminal task's own
    lines can never change again -- this cache entry is valid indefinitely,
    no TTL needed. A running/incomplete trace is never cached, since its
    lines could still be arriving; caching it would risk serving a stale,
    incomplete picture forever.

    Callers must only invoke this when the lift/rotation fetch itself
    actually succeeded (see get_task_trace's `enrichment_ok`) -- caching a
    transient SSH failure's swallowed-to-`[]` result would be
    indistinguishable from a real "this task has zero lift/rotation
    events", permanently hiding real data behind a cache hit that never
    retries (confirmed real: task b55bbb47-6d71-4222-9085-d3e1006042ac).
    """
    if trace.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
        return
    with SessionLocal() as session:
        row = session.get(TaskTraceRow, task_id) or TaskTraceRow(task_id=task_id)
        row.request_id = request_id
        row.butler_ip = butler_ip
        row.task_type = task_type
        row.butler_id = trace.butler_id
        row.status = trace.status.value
        row.created_at = trace.created_at
        row.dispatched_at = trace.dispatched_at
        row.completed_at = trace.completed_at
        row.total_duration_seconds = trace.total_duration_seconds
        row.task_lines_json = task_lines
        row.lift_lines_json = raw_lift_lines
        row.rotation_lines_json = raw_rotation_lines
        row.fetched_at = datetime.utcnow()
        session.add(row)
        session.commit()


class TaskLookupRequest(BaseModel):
    butler_ip: str
    ssh_user: str = "gor"
    task_id: str | None = None
    request_id: str | None = None


class WindowScanRequest(BaseModel):
    butler_ip: str
    ssh_user: str = "gor"
    from_time: datetime
    to_time: datetime


class FullScanRequest(BaseModel):
    butler_ip: str
    ssh_user: str = "gor"
    lookback_hours: int = Field(default=DEFAULT_SCAN_LOOKBACK_HOURS, le=MAX_SCAN_LOOKBACK_DAYS * 24)
    confirmed_expensive: bool = False


@router.post("/api/connectivity-check")
def connectivity_check(butler_ip: str, ssh_user: str = "gor"):
    target = SshTarget(ip=butler_ip, user=ssh_user)
    try:
        check_connectivity(target)
    except SshCommandError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Passwordless SSH not working for {ssh_user}@{butler_ip}: {exc}",
        ) from exc
    return {"ok": True}


@router.post("/api/task")
def get_task_trace(req: TaskLookupRequest):
    """Mode 1: task_id (or request_id) given -> single TaskTrace.

    Checks the local cache (see TaskTraceRow) before making ANY SSH call --
    a hit here means zero remote round trips and zero load on the butler
    box, not just a faster response. Only completed/failed traces are ever
    cached (see _maybe_cache_trace), so a hit is always safe to serve as-is.
    """
    if not req.task_id and not req.request_id:
        raise HTTPException(400, "Provide either task_id or request_id")

    if req.task_id:
        cached = _load_cached_trace(req.butler_ip, req.task_id)
        if cached is not None:
            return cached

    target = SshTarget(ip=req.butler_ip, user=req.ssh_user)
    try:
        log_files = list_debug_log_files(target)
        if not log_files:
            raise HTTPException(404, f"No debug.log files found on {req.butler_ip}")

        if req.task_id:
            search_id = req.task_id
        else:
            req_id_lines = grep_logs(target, req.request_id, log_files)
            resolved = resolve_task_id_from_request_id(req.request_id, req_id_lines)
            if resolved is None:
                raise HTTPException(
                    404,
                    f"request_id {req.request_id} found but no task_id resolved yet "
                    "(task creation may not have completed, or logs have rotated past it)",
                )
            search_id = resolved.task_id
            # Same cache the task_id-direct path checks above -- a
            # request_id lookup still needed the (cheap) resolution grep
            # just now, but this skips the expensive task_lines/lift/
            # rotation greps below if this task_id was already cached from
            # an earlier direct lookup.
            cached = _load_cached_trace(req.butler_ip, search_id)
            if cached is not None:
                return cached

        task_lines = grep_logs(target, search_id, log_files)
        if not task_lines:
            raise HTTPException(404, f"No log lines found for task_id {search_id}")

        request_id_found = find_request_id(task_lines) or req.request_id
        # task_type: prefer what id_resolver found (works for types created
        # via transport_request_event_handler); otherwise sniff it directly
        # off the grepped lines themselves, since every task type restates
        # its own type inline (e.g. `Task={relay_group_task,<<"KEY">>}` /
        # `TaskId: {relay_pps_task,<<"KEY">>}`) regardless of how it was
        # created. Only falls back to relay_pps_task (the one type proven
        # against a real trace) if neither signal is present.
        task_type = _sniff_task_type(task_lines, search_id) or "relay_pps_task"
        if request_id_found:
            resolved = resolve_task_id_from_request_id(request_id_found, task_lines)
            if resolved:
                task_type = resolved.task_type

        trace = _build_trace(search_id, task_type, request_id_found, task_lines)

        raw_lift_lines: list[str] = []
        raw_rotation_lines: list[str] = []
        # Tracks whether the lift/rotation enrichment is trustworthy enough
        # to cache -- a transient SSH failure anywhere in this fetch must
        # never get cached as "this task genuinely has zero lift/rotation
        # events" (see _fetch_raw_lift_lines's docstring for the real
        # incident this fixes). Defaults True: no window at all means
        # there's genuinely nothing to enrich, not a failed fetch.
        enrichment_ok = True
        window = _task_time_window(trace)
        if window is not None:
            try:
                candidate_files = _candidate_log_files(target, window[0])
            except SshCommandError:
                candidate_files = []
                enrichment_ok = False
            raw_lift_lines, lift_ok = _fetch_raw_lift_lines(target, trace, candidate_files)
            raw_rotation_lines, rotation_ok = _fetch_raw_rotation_lines(target, trace, candidate_files)
            enrichment_ok = enrichment_ok and lift_ok and rotation_ok
        _maybe_reclassify_relay_group_completion(trace, raw_lift_lines)
        _apply_lift_rotation_lines(trace, task_lines, raw_lift_lines, raw_rotation_lines)

        if enrichment_ok:
            _maybe_cache_trace(
                req.butler_ip, search_id, request_id_found, task_type, trace, task_lines, raw_lift_lines, raw_rotation_lines
            )
        return _trace_to_dict(trace)
    except SshCommandError as exc:
        raise HTTPException(502, str(exc)) from exc


class FullLogsResponse(BaseModel):
    task_id: str
    butler_id: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    line_count: int
    lines: list[str]


@router.post("/api/task/full-logs", response_model=FullLogsResponse)
def get_task_full_logs(req: TaskLookupRequest):
    """EVERY raw log line in the task's own time window, from the first
    line to the last -- irrespective of butler_id, task_id, or any known
    marker pattern. Not filtered to this task's own bot at all: anything
    else logged in that same window (another bot, an MHS-level event, a
    different subsystem entirely) comes through too, since it's still
    context for what was happening at the time. This is the deliberate
    escape hatch for "what did the box ACTUALLY log", including modules/
    messages nothing in this codebase has a parser for at all -- export-
    only (see TaskSwimlane.tsx's "Download all logs" button), never part
    of trace-building or caching.
    """
    if not req.task_id and not req.request_id:
        raise HTTPException(400, "Provide either task_id or request_id")

    target = SshTarget(ip=req.butler_ip, user=req.ssh_user)
    try:
        trace = _load_cached_trace_object(req.butler_ip, req.task_id) if req.task_id else None
        if trace is None:
            trace, _task_lines = _resolve_task_lines_and_trace(target, req)

        window = _task_time_window(trace)
        if window is None:
            return FullLogsResponse(task_id=trace.task_id, butler_id=trace.butler_id, line_count=0, lines=[])

        window_start, window_end = window
        candidate_files = _candidate_log_files(target, window_start)
        # "^" matches every line unconditionally (a zero-width start-of-
        # line anchor) -- the whole point here is no content filter at
        # all, just every line in these files, trimmed to the window below
        # by timestamp.
        all_lines = grep_logs(target, "^", candidate_files, timeout=180)
        in_window = _filter_lines_to_window(all_lines, window_start, window_end)
        return FullLogsResponse(
            task_id=trace.task_id,
            butler_id=trace.butler_id,
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
            line_count=len(in_window),
            lines=in_window,
        )
    except SshCommandError as exc:
        raise HTTPException(502, str(exc)) from exc


class BenchmarkSubEventResult(BaseModel):
    kind: str  # "lift" | "rotation" | "fork"
    label: str
    duration_seconds: float
    threshold_seconds: float
    passed: bool
    sequence_violation: bool = False


class SaveBenchmarkResultRequest(BaseModel):
    task_id: str
    task_type: str | None = None
    butler_ip: str | None = None
    thresholds: dict
    results: list[BenchmarkSubEventResult]


@router.post("/api/benchmark-result")
def save_benchmark_result(req: SaveBenchmarkResultRequest):
    """Explicit, user-triggered save (see TaskSwimlane.tsx's "Save
    benchmark result" button) -- never written automatically just because
    a task was viewed. task_id is not unique here: saving the same task
    again (e.g. after adjusting thresholds) adds a new row, preserving
    history rather than overwriting it.
    """
    pass_count = sum(1 for r in req.results if r.passed and not r.sequence_violation)
    fail_count = len(req.results) - pass_count
    with SessionLocal() as session:
        row = BenchmarkResultRow(
            task_id=req.task_id,
            task_type=req.task_type,
            butler_ip=req.butler_ip,
            recorded_at=datetime.utcnow(),
            thresholds_json=req.thresholds,
            results_json=[r.model_dump() for r in req.results],
            pass_count=pass_count,
            fail_count=fail_count,
        )
        session.add(row)
        session.commit()
        return {"id": row.id, "recorded_at": row.recorded_at.isoformat(), "pass_count": pass_count, "fail_count": fail_count}


@router.get("/api/benchmark-result/{task_id}")
def get_benchmark_results(task_id: str):
    """Only ever called when the user explicitly asks to view saved
    results for a task (see TaskSwimlane.tsx's "View saved results"
    button) -- there is no automatic history surfacing anywhere.
    """
    with SessionLocal() as session:
        rows = (
            session.query(BenchmarkResultRow)
            .filter(BenchmarkResultRow.task_id == task_id)
            .order_by(BenchmarkResultRow.recorded_at.desc())
            .all()
        )
        return {
            "task_id": task_id,
            "results": [
                {
                    "id": row.id,
                    "recorded_at": row.recorded_at.isoformat(),
                    "task_type": row.task_type,
                    "butler_ip": row.butler_ip,
                    "thresholds": row.thresholds_json,
                    "pass_count": row.pass_count,
                    "fail_count": row.fail_count,
                    "results": row.results_json,
                }
                for row in rows
            ],
        }


@router.post("/api/window")
def scan_window(req: WindowScanRequest):
    """Mode 2: time range given -> enqueue a batch job.

    Actual RQ wiring (job.py) intentionally not implemented in this pass -
    see PLAN.md "Job/queueing model". This endpoint validates the request
    and returns a job_id placeholder; wire to RQ's `enqueue()` next.
    """
    if req.to_time <= req.from_time:
        raise HTTPException(400, "to_time must be after from_time")
    job_id = str(uuid.uuid4())
    # TODO: enqueue `_run_window_scan(req)` via RQ, persist ScanJobRow.
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/scan")
def full_scan(req: FullScanRequest):
    """Mode 3: neither task_id nor time range given -> bounded scan.

    Never truly unbounded (see PLAN.md) - defaults to last 24h; widening
    past that requires confirmed_expensive=true and is still capped at
    MAX_SCAN_LOOKBACK_DAYS server-side regardless of what's requested.

    Runs synchronously (no RQ wiring exists yet) - acceptable for the
    default 24h window, same call as /api/task makes for a single task.
    Returns a presentable task_id/bot/relay_position summary for every
    relay_group_task and relay_pps_task started in the window - see
    parsers/task_summary.py for how this is derived from one bulk grep
    instead of a per-task lookup.
    """
    if req.lookback_hours > DEFAULT_SCAN_LOOKBACK_HOURS and not req.confirmed_expensive:
        raise HTTPException(
            400,
            f"Widening past {DEFAULT_SCAN_LOOKBACK_HOURS}h requires confirmed_expensive=true "
            f"(hard cap: {MAX_SCAN_LOOKBACK_DAYS} days)",
        )
    window_start = datetime.utcnow() - timedelta(hours=req.lookback_hours)

    target = SshTarget(ip=req.butler_ip, user=req.ssh_user)
    try:
        files_with_mtime = list_debug_log_files_with_mtime(target)
        candidate_files = [f for f, mtime in files_with_mtime if mtime >= window_start]
        if not candidate_files:
            return {"window_start": window_start.isoformat(), "tasks": []}

        raw = grep_logs(target, TASK_SUMMARY_GREP_PATTERN, candidate_files, timeout=120)
    except SshCommandError as exc:
        raise HTTPException(502, str(exc)) from exc

    parsed = [p for p in parse_lines(raw) if p.timestamp >= window_start]
    summaries = [
        s
        for s in build_task_summaries(parsed)
        if s.task_type in TASK_SUMMARY_TYPES and s.created_at >= window_start
    ]
    summaries.sort(key=lambda s: s.created_at, reverse=True)

    return {
        "window_start": window_start.isoformat(),
        "tasks": [
            {
                "task_id": s.task_id,
                "task_type": s.task_type,
                "bot_id": s.bot_id,
                "created_at": s.created_at.isoformat(),
                "relay_position": s.relay_position,
                "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
                "is_bot_current_task": s.is_bot_current_task,
            }
            for s in summaries
        ],
    }


# Bounds how many distinct bots' full-window lift/rotation lines get
# fetched for one aggregate-stats call -- each is its own SSH round trip
# (60-120s), so an unbounded fleet would make this call impractically slow.
# Any bots past this cap are dropped, never silently -- see
# distinct_bots_skipped in the response.
MAX_BOTS_FOR_AGGREGATE = 10


class AggregateStatsRequest(BaseModel):
    butler_ip: str
    ssh_user: str = "gor"
    lookback_hours: int = Field(default=DEFAULT_SCAN_LOOKBACK_HOURS, le=MAX_SCAN_LOOKBACK_DAYS * 24)


@router.post("/api/aggregate-stats")
def aggregate_stats(req: AggregateStatsRequest):
    """Average simultaneous-lift time (grouped by target fork height) and
    average rotation time across every relay_pps_task in the lookback
    window -- reuses the same bulk task_summary scan /api/scan does, then
    does ONE additional lift+rotation grep per distinct bot involved (not
    per task, which wouldn't scale to a window with 100+ tasks) -- see
    parsers/aggregate_stats.py for the averaging itself.
    """
    window_start = datetime.utcnow() - timedelta(hours=req.lookback_hours)
    target = SshTarget(ip=req.butler_ip, user=req.ssh_user)

    empty_response = {
        "window_start": window_start.isoformat(),
        "task_count": 0,
        "tasks_with_lift_data": 0,
        "tasks_with_rotation_data": 0,
        "lift_by_target_height_mm": {},
        "rotation": None,
        "distinct_bots_processed": [],
        "distinct_bots_skipped": [],
    }

    try:
        files_with_mtime = list_debug_log_files_with_mtime(target)
        candidate_files = [f for f, mtime in files_with_mtime if mtime >= window_start]
        if not candidate_files:
            return empty_response
        raw = grep_logs(target, TASK_SUMMARY_GREP_PATTERN, candidate_files, timeout=120)
    except SshCommandError as exc:
        raise HTTPException(502, str(exc)) from exc

    parsed = [p for p in parse_lines(raw) if p.timestamp >= window_start]
    summaries = [
        s
        for s in build_task_summaries(parsed)
        if s.task_type == "relay_pps_task" and s.created_at >= window_start
    ]
    if not summaries:
        return empty_response

    pad = timedelta(seconds=_TIGHT_WINDOW_PAD_SECONDS)
    task_windows = [
        TaskWindow(
            task_id=s.task_id,
            bot_id=s.bot_id,
            start=s.created_at - pad,
            end=(s.last_seen_at or s.created_at) + pad,
        )
        for s in summaries
    ]

    distinct_bots = sorted({tw.bot_id for tw in task_windows})
    distinct_bots_skipped = distinct_bots[MAX_BOTS_FOR_AGGREGATE:]
    distinct_bots_processed = distinct_bots[:MAX_BOTS_FOR_AGGREGATE]
    task_windows = [tw for tw in task_windows if tw.bot_id in distinct_bots_processed]

    lift_events_by_bot: dict[str, list] = {}
    rotation_events_by_bot: dict[str, list] = {}
    for bot_id in distinct_bots_processed:
        bot_windows = [tw for tw in task_windows if tw.bot_id == bot_id]
        bot_start = min(tw.start for tw in bot_windows)
        bot_end = max(tw.end for tw in bot_windows)
        try:
            bot_candidate_files = [f for f, mtime in files_with_mtime if mtime >= bot_start]
            if not bot_candidate_files:
                continue

            lift_raw = grep_bot_lift_lines(target, bot_id, bot_candidate_files, timeout=120)
            lift_parsed = [p for p in parse_lines(lift_raw) if bot_start <= p.timestamp <= bot_end]
            lift_events_by_bot[bot_id] = build_lift_events(lift_parsed)

            rotation_raw = grep_bot_rotation_lines(target, bot_id, bot_candidate_files, timeout=120)
            rotation_parsed = [p for p in parse_lines(rotation_raw) if bot_start <= p.timestamp <= bot_end]
            rotation_events_by_bot[bot_id] = build_rotation_events(rotation_parsed)
        except SshCommandError:
            continue  # best-effort per bot -- one bot's grep failing shouldn't sink the whole call

    result = compute_lift_rotation_aggregates(task_windows, lift_events_by_bot, rotation_events_by_bot)
    result["window_start"] = window_start.isoformat()
    result["distinct_bots_processed"] = distinct_bots_processed
    result["distinct_bots_skipped"] = distinct_bots_skipped
    return result


def _trace_to_dict(trace) -> dict:
    return {
        "request_id": trace.request_id,
        "task_id": trace.task_id,
        "task_type": trace.task_type,
        "butler_id": trace.butler_id,
        "status": trace.status.value,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "dispatched_at": trace.dispatched_at.isoformat() if trace.dispatched_at else None,
        "completed_at": trace.completed_at.isoformat() if trace.completed_at else None,
        "queued_duration_seconds": trace.queued_duration_seconds,
        "total_duration_seconds": trace.total_duration_seconds,
        "cycle_duration_seconds": trace.cycle_duration_seconds,
        "tote_ids": trace.tote_ids,
        "has_warnings_or_errors": trace.has_warnings_or_errors,
        "warning_lines": trace.warning_lines,
        "phases": [
            {**p, "timestamp": p["timestamp"].isoformat()} for p in trace.phase_durations()
        ],
        "events": [
            {
                "timestamp": ev.timestamp.isoformat(),
                "module": ev.module,
                "function": ev.function,
                "phase_label": ev.phase_label,
                "attr_tag": ev.attr_tag,
                "bot_id": ev.bot_id,
                "confidence": ev.confidence.value,
                "raw_line": ev.raw_line,
            }
            for ev in trace.events
        ],
        "lift_events": [
            {
                "bot_id": le.bot_id,
                "order_sent_at": le.order_sent_at.isoformat() if le.order_sent_at else None,
                "logged_complete_at": le.logged_complete_at.isoformat(),
                "target_height_mm": le.target_height_mm,
                "corrected_complete_at": le.corrected_complete_at.isoformat() if le.corrected_complete_at else None,
                "correction_method": le.correction_method,
                "buffer_ms": le.buffer_ms,
                "understated_by_seconds": le.understated_by_seconds,
                "confidence": le.confidence.value,
                "direction": le.direction,
                "context_label": le.context_label,
                "coordinate": list(le.coordinate) if le.coordinate else None,
            }
            for le in trace.lift_events
        ],
        "rotation_events": [
            {
                "bot_id": re_.bot_id,
                "timestamp": re_.timestamp.isoformat(),
                "coordinate": list(re_.coordinate) if re_.coordinate else None,
                "duration_ms": re_.duration_ms,
                "confidence": re_.confidence.value,
                "significance": re_.significance,
                "method": re_.method,
                "context_label": re_.context_label,
            }
            for re_ in trace.rotation_events
        ],
        "fork_adjustment_events": [
            {
                "bot_id": fe.bot_id,
                "timestamp": fe.timestamp.isoformat(),
                "started_at": fe.started_at.isoformat() if fe.started_at else None,
                "from_height_mm": fe.from_height_mm,
                "to_height_mm": fe.to_height_mm,
                "direction": fe.direction,
                "confidence": fe.confidence.value,
                "label": fe.label,
                "coordinate": list(fe.coordinate) if fe.coordinate else None,
            }
            for fe in trace.fork_adjustment_events
        ],
        "charge_timing": _charge_timing_to_dict(trace.charge_timing),
    }


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _charge_timing_to_dict(timing) -> dict | None:
    if timing is None:
        return None
    return {
        "assigned_at": _iso(timing.assigned_at),
        "reached_charger_reinit_at": _iso(timing.reached_charger_reinit_at),
        "reached_charger_at": _iso(timing.reached_charger_at),
        "charging_started_at": _iso(timing.charging_started_at),
        "charging_complete_at": _iso(timing.charging_complete_at),
        "return_dispatched_at": _iso(timing.return_dispatched_at),
        "return_reached_charger_reinit_at": _iso(timing.return_reached_charger_reinit_at),
        "parked_at": _iso(timing.parked_at),
        "assigned_to_reinit_seconds": timing.assigned_to_reinit_seconds,
        "reinit_to_charger_seconds": timing.reinit_to_charger_seconds,
        "docked_to_charging_started_seconds": timing.docked_to_charging_started_seconds,
        "outbound_travel_seconds": timing.outbound_travel_seconds,
        "charging_duration_seconds": timing.charging_duration_seconds,
        "charging_stop_to_reinit_seconds": timing.charging_stop_to_reinit_seconds,
        "reinit_to_parked_seconds": timing.reinit_to_parked_seconds,
        "return_travel_seconds": timing.return_travel_seconds,
        "total_seconds": timing.total_seconds,
        "battery_pct_at_charger_arrival": timing.battery_pct_at_charger_arrival,
        "battery_pct_at_charging_complete": timing.battery_pct_at_charging_complete,
        "graceful_stop_at": _iso(timing.graceful_stop_at),
        "graceful_stop_reason": timing.graceful_stop_reason,
        "charging_stopped_via_api": timing.charging_stopped_via_api,
    }
