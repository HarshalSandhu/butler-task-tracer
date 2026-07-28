"""RequestId -> real TaskId/MainTaskKey resolution.

Confirmed this session by manual trace: RequestId is logged first
(transport_request_event_handler.erl:554, "#Triggered task creation:
RequestId ~p"). The real TaskId is NOT co-logged on that same line - it only
shows up later, once storage completes, in one of two forms seen in a
grep-by-RequestId result set:

  1. "#Task created , Task-type relay_pps_task Task <<"5fbc..."\">>
     Request-Id <<"4899..."\">> DestinationType <<"pps"\">>"
     (transport_request_event_handler:create_ttp_tote_task_for_pps)

  2. The pgsql_adapter:create_transport_request save-array line, which
     embeds both ids positionally:
     ["4899...","created","tote","{...}","relay_pps_task","5fbc...","put",...]
     (RequestId at position 0, task_type at position 4, TaskId at position 5)

This module only covers task types dispatched through
transport_request_event_handler (confirmed: relay_pps_task; per PLAN.md,
likely also relay_group_task/tote_move_task/conveyor_move_task/
port_move_task since they share the same transport-request flow). Task
types NOT created via a transport request (chargetask, bot_transport_task,
early_dispatch_task, rangergrouptask) need their own creation-marker logic -
not yet captured with real log samples this session, so they fall back to
the correlation.py heuristic instead of a direct resolver here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable

_TASK_CREATED_RE = re.compile(
    r'#Task created\s*,\s*Task-type\s+(?P<task_type>\S+)\s+Task\s+<<"(?P<task_id>[^"]+)">>'
    r'\s+Request-Id\s+<<"(?P<request_id>[^"]+)">>'
)

# Positional fallback: RequestId,...,task_type,task_id as the 1st/5th/6th
# quoted elements of the pgsql_adapter save-array line.
_SAVE_ARRAY_RE = re.compile(
    r'\["(?P<request_id>[^"]+)","[^"]*","[^"]*","[^"]*","(?P<task_type>[^"]*)","(?P<task_id>[^"]*)"'
)

_TRIGGERED_RE = re.compile(r'#Triggered task creation:\s*RequestId\s+<<"(?P<request_id>[^"]+)">>')


@dataclass
class ResolvedTaskId:
    request_id: str
    task_id: str
    task_type: str


def find_request_id(lines: "Iterable[str]") -> str | None:
    """First "#Triggered task creation" line's RequestId, if present."""
    for line in lines:
        m = _TRIGGERED_RE.search(line)
        if m:
            return m.group("request_id")
    return None


def resolve_task_id_from_request_id(
    request_id: str, lines: "Iterable[str]"
) -> ResolvedTaskId | None:
    """Given lines already grepped by `request_id`, find the real task_id.

    Tries the explicit "#Task created" line first (most precise, gives
    task_type directly); falls back to the positional save-array line.
    Returns None if neither pattern matches - callers should treat this as
    "task creation not yet observed in this log window", not an error.
    """
    for line in lines:
        m = _TASK_CREATED_RE.search(line)
        if m and m.group("request_id") == request_id:
            return ResolvedTaskId(
                request_id=request_id,
                task_id=m.group("task_id"),
                task_type=m.group("task_type"),
            )
    for line in lines:
        m = _SAVE_ARRAY_RE.search(line)
        if m and m.group("request_id") == request_id:
            return ResolvedTaskId(
                request_id=request_id,
                task_id=m.group("task_id"),
                task_type=m.group("task_type"),
            )
    return None
