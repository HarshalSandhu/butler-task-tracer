"""HTTP API surface - see PLAN.md "Two operating modes + a bounded third".

Note what is NOT here: there is no endpoint, field, or model anywhere in
this module that accepts a private key, passphrase, or any credential
beyond `butler_ip`/`ssh_user`. See app/ssh/executor.py's module docstring
for the invariant this enforces.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.parsers.id_resolver import find_request_id, resolve_task_id_from_request_id
from app.parsers.trace_builder import build_trace
from app.ssh.executor import SshCommandError, SshTarget, check_connectivity, grep_logs, list_debug_log_files

router = APIRouter()

MAX_SCAN_LOOKBACK_DAYS = 30
DEFAULT_SCAN_LOOKBACK_HOURS = 24


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
    """Mode 1: task_id (or request_id) given -> single TaskTrace."""
    if not req.task_id and not req.request_id:
        raise HTTPException(400, "Provide either task_id or request_id")

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

        task_lines = grep_logs(target, search_id, log_files)
        if not task_lines:
            raise HTTPException(404, f"No log lines found for task_id {search_id}")

        request_id_found = find_request_id(task_lines) or req.request_id
        # task_type: prefer what id_resolver found; otherwise default to
        # relay_pps_task (only resolver implemented today - see
        # parsers/task_types/__init__.py KNOWN_UNIMPLEMENTED_TYPES).
        task_type = "relay_pps_task"
        if request_id_found:
            resolved = resolve_task_id_from_request_id(request_id_found, task_lines)
            if resolved:
                task_type = resolved.task_type

        trace = build_trace(
            task_id=search_id,
            task_type=task_type,
            request_id=request_id_found,
            raw_lines=task_lines,
        )
        return _trace_to_dict(trace)
    except SshCommandError as exc:
        raise HTTPException(502, str(exc)) from exc


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
    """
    if req.lookback_hours > DEFAULT_SCAN_LOOKBACK_HOURS and not req.confirmed_expensive:
        raise HTTPException(
            400,
            f"Widening past {DEFAULT_SCAN_LOOKBACK_HOURS}h requires confirmed_expensive=true "
            f"(hard cap: {MAX_SCAN_LOOKBACK_DAYS} days)",
        )
    from_time = datetime.utcnow() - timedelta(hours=req.lookback_hours)
    job_id = str(uuid.uuid4())
    # TODO: enqueue via RQ, same as scan_window.
    return {"job_id": job_id, "status": "queued", "effective_from": from_time.isoformat()}


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
    }
