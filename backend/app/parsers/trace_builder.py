"""Assembles a full TaskTrace from raw log lines already grepped by task_id.

This is the orchestration layer tying together line_parser, the
task_types registry, and terminal_state - given every line matching a
known task_id (already resolved via id_resolver against a RequestId, or
supplied directly if the caller already has the task_id), build the
ordered TaskTrace the frontend renders.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.models import Confidence, TaskEvent, TaskStatus, TaskTrace
from app.parsers.generic_movement import extract_butler_id
from app.parsers.line_parser import parse_lines
from app.parsers.task_types import get_resolver
from app.parsers.terminal_state import classify

_CREATED_MARKER = "#Task created"
_STARTED_MARKER = 'event=<<"started">>'
_DISPATCH_MARKER = "SubTask_list:"

# Appears in both task types' subtask specs in the tagged form
# `tote_id,<<"00000009">>` (load_tote/unload_tote/pps_control/etc, confirmed
# against a real relay_pps_task trace) -- a relay_group_task can carry
# several distinct tote_ids across its batched tote legs, so this collects
# all of them, in first-seen order, rather than assuming exactly one.
_TOTE_ID_RE = re.compile(r'tote_id,<<"(?P<tote_id>[^"]+)">>')

_NOTABLE_LEVELS = {"warning", "error"}


def build_trace(
    task_id: str,
    task_type: str,
    request_id: str | None,
    raw_lines: list[str],
) -> TaskTrace:
    """`raw_lines` should be every debug.log line matching `task_id` (or
    `request_id` for the earliest creation-phase lines that predate the
    task_id being known - see id_resolver.py), already in chronological
    order (grep output is naturally file-order, which is timestamp-order
    within one file).
    """
    parsed = list(parse_lines(raw_lines))
    resolver = get_resolver(task_type)

    events: list[TaskEvent] = []
    butler_id: str | None = None
    created_at: datetime | None = None
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
    tote_ids: list[str] = []
    warning_lines: list[str] = []

    for p in parsed:
        if created_at is None and _CREATED_MARKER in p.message:
            created_at = p.timestamp

        if dispatched_at is None and (
            _STARTED_MARKER in p.message or _DISPATCH_MARKER in p.message
        ):
            dispatched_at = p.timestamp

        for m in _TOTE_ID_RE.finditer(p.message):
            tote_id = m.group("tote_id")
            if tote_id not in tote_ids:
                tote_ids.append(tote_id)

        if p.level.lower() in _NOTABLE_LEVELS:
            warning_lines.append(p.raw_line)

        movement = resolver.parse_movement(p.message) if resolver else None
        tracing = resolver.parse_tracing_event(p.message) if resolver else None

        if movement is not None:
            butler_id = movement["bot_id"]
            events.append(
                TaskEvent(
                    timestamp=p.timestamp,
                    module=p.module,
                    function=p.function,
                    line_no=p.line_no,
                    raw_line=p.raw_line,
                    phase_label=f"reached_{movement['attr']}",
                    attr_tag=movement["attr"],
                    bot_id=movement["bot_id"],
                    confidence=Confidence.EXACT,
                    coordinate=movement.get("coordinate"),
                )
            )
        elif tracing is not None:
            events.append(
                TaskEvent(
                    timestamp=p.timestamp,
                    module=p.module,
                    function=p.function,
                    line_no=p.line_no,
                    raw_line=p.raw_line,
                    phase_label=tracing["event_name"],
                    attr_tag=None,
                    bot_id=butler_id,
                    confidence=Confidence.EXACT,
                )
            )

    if butler_id is None:
        # Fallback for a log format whose movement-arrival line doesn't
        # carry a semantic attr label the task type's own EXACT resolver
        # can key off of (see parsers/generic_movement.py) -- every line
        # restates butler_id=N as a plain prefix regardless of format, so
        # this is never wrong, just less specific than deriving it from a
        # real movement event.
        butler_id = extract_butler_id(raw_lines)

    status = classify([p.message for p in parsed], task_id=task_id)
    if status == TaskStatus.COMPLETED and parsed:
        completed_at = parsed[-1].timestamp

    return TaskTrace(
        request_id=request_id,
        task_id=task_id,
        task_type=task_type,
        butler_id=butler_id,
        events=events,
        status=status,
        created_at=created_at,
        dispatched_at=dispatched_at,
        completed_at=completed_at,
        tote_ids=tote_ids,
        warning_lines=warning_lines,
    )
