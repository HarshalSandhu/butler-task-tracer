"""Assembles a full TaskTrace from raw log lines already grepped by task_id.

This is the orchestration layer tying together line_parser, the
task_types registry, and terminal_state - given every line matching a
known task_id (already resolved via id_resolver against a RequestId, or
supplied directly if the caller already has the task_id), build the
ordered TaskTrace the frontend renders.
"""

from __future__ import annotations

from datetime import datetime

from app.models import Confidence, TaskEvent, TaskStatus, TaskTrace
from app.parsers.line_parser import parse_lines
from app.parsers.task_types import get_resolver
from app.parsers.terminal_state import classify

_CREATED_MARKER = "#Task created"
_STARTED_MARKER = 'event=<<"started">>'
_DISPATCH_MARKER = "SubTask_list:"


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

    for p in parsed:
        if created_at is None and _CREATED_MARKER in p.message:
            created_at = p.timestamp

        if dispatched_at is None and (
            _STARTED_MARKER in p.message or _DISPATCH_MARKER in p.message
        ):
            dispatched_at = p.timestamp

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

    status = classify([p.message for p in parsed])
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
    )
