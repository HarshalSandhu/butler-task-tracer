"""Generic, format-agnostic movement/phase reconstruction -- a fallback
for software versions/log formats that don't emit the exact-confidence
`goto_barcode_completed: bot X reached {Y,Z} (attr=W), Task=...,
MainTaskKey=...` line every task_types/*.py resolver is built around (see
their own docstrings).

Confirmed real (task d0461a46-a3b2-4f64-803f-9ab55bf77f8e, bot 134, a
differently-versioned server): this version logs arrivals via
`navigator_agent:reached_destination` instead -- a raw {x,y} coordinate
with NO semantic attr label, NO task_id, NO MainTaskKey at all. This is a
structurally different mechanism, not just a line-number/wording change,
so task_types/relay_pps_task.py's own resolver correctly finds nothing at
all for this trace (confirmed: butler_id/phases/events all empty before
this module existed).

Two real signals combine to recover the same information the exact path
gets for free:

  1. The task's own subtask-tuple lines -- both the upfront `SubTask_list`
     dump AND the one-at-a-time "The Current SubTask is : {subtask,...}"
     progress lines (both grepped by task_id already, see
     trace_builder.py) -- state each planned goto_barcode/
     compute_parallel_lift_goto_barcode step's own target coordinate AND
     (when known) its semantic destination, e.g. `destination_info,
     {relay_storable,<<"TLOC_...">>,without_tote}` or `{pps_id,130}`.
     Confirmed real: these coordinates match the ACTUAL reached_destination
     arrivals exactly (task d0461a46...: planned {108,41} for the pickup
     step -> real arrival at {108,41} ~66 seconds later; planned {15,45}
     for the drop step, itself only ever stated in a later "Current
     SubTask" line, not the upfront dump -> real arrival at {15,45}).
  2. `reached_destination` itself, fetched butler_id-scoped (reusing the
     same #recv/turn_step fetch rotation_events.py already makes -- see
     ssh/executor.py's _ROTATION_MARKER_PATTERN) and bounded to the task's
     own time window, gives the real arrival TIMESTAMP for each
     coordinate.

A coordinate with no resolvable destination_info (e.g. an exit-queue leg,
confirmed real: {48,168} has a target_coord_with_dir but no
destination_info anywhere in this trace) is simply dropped rather than
shown with a fabricated label -- same principle as every other module in
this codebase: never claim something the log itself didn't support.

Always Confidence.HEURISTIC: attribution is butler_id + time-window, same
as every other line type that doesn't restate a task_id (lift/rotation
events, VTM's completion-status line, etc.).
"""

from __future__ import annotations

import re

from app.models import Confidence, TaskEvent
from app.parsers.line_parser import ParsedLine

_GENERIC_BUTLER_ID_RE = re.compile(r"butler_id=(?P<bot_id>\d+)")


def extract_butler_id(raw_lines: list[str]) -> str | None:
    """Format-agnostic fallback: every line restates butler_id=N as a
    plain prefix regardless of task type or log-format version (confirmed
    across every real capture this session has seen) -- used only when
    the task type's own EXACT movement resolver (task_types/*.py) found
    nothing to key butler_id off of.
    """
    for line in raw_lines:
        m = _GENERIC_BUTLER_ID_RE.search(line)
        if m:
            return m.group("bot_id")
    return None


# Each subtask entry has the shape {subtask,Name,Name,[Args...]} -- the
# name is repeated as both the "type" and "name" fields, confirmed
# universal across every real subtask tuple seen this session. Splitting
# the line into per-subtask chunks (rather than one flat regex scan for
# target_coord_with_dir/destination_info across the whole line) is what
# lets a coordinate be correctly paired with ONLY its own subtask's
# destination_info, not a different subtask's that happens to appear
# later in the same dump.
_SUBTASK_START_RE = re.compile(r"\{subtask,(\w+),\1,\[")
_TARGET_COORD_RE = re.compile(r"target_coord_with_dir,\{\{(-?\d+),(-?\d+)\}")
_DESTINATION_INFO_RE = re.compile(r"destination_info,\{(\w+)")

# destination_info's own leading atom -> this codebase's existing attr
# vocabulary (see event_context.py's KEY_WAYPOINT_ATTRS/PICK_DROP_ATTR).
# Confirmed real (task d0461a46...): relay_storable for both the
# with_tote and without_tote legs -- this newer subtask goes straight to
# the pick/drop slot itself, no separate io_point staging step observed
# the way the exact-confidence path distinguishes relay_storable_io_point
# from relay_storable -- so this fallback can't recover that same
# granularity, only the slot-level waypoint itself.
_DESTINATION_LABELS = {
    "relay_storable": "relay_storable",
    "pps_id": "pps",
}


def extract_waypoint_labels(raw_lines: list[str]) -> dict[tuple[int, int], str]:
    """{(x, y): attr} built from every subtask-tuple line in the task's
    own grep -- both the upfront SubTask_list dump and the later
    one-at-a-time "Current SubTask" progress lines, since a destination
    only stated in the LATER form (confirmed real: the {15,45} drop leg)
    would otherwise be missed if only the upfront dump were scanned.
    """
    labels: dict[tuple[int, int], str] = {}
    for line in raw_lines:
        starts = [m.start() for m in _SUBTASK_START_RE.finditer(line)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(line)
            chunk = line[start:end]
            coord_m = _TARGET_COORD_RE.search(chunk)
            if not coord_m:
                continue
            dest_m = _DESTINATION_INFO_RE.search(chunk)
            if not dest_m:
                continue
            label = _DESTINATION_LABELS.get(dest_m.group(1))
            if label is None:
                continue
            labels[(int(coord_m.group(1)), int(coord_m.group(2)))] = label
    return labels


_REACHED_DESTINATION_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) Butler: \d+ reached final destination: "
    r"\{\{\{(?P<x>-?\d+),(?P<y>-?\d+)\},[^}]*\},[^}]*\}, took:"
)


def build_generic_movement_events(
    lines: list[ParsedLine],
    waypoint_labels: dict[tuple[int, int], str],
) -> list[TaskEvent]:
    """One TaskEvent per real `reached_destination` arrival that resolves
    to a known waypoint (see extract_waypoint_labels). `lines` should
    already be scoped to one bot's own time window (same caller
    responsibility as build_lift_events/build_rotation_events).
    """
    events: list[TaskEvent] = []
    for p in lines:
        m = _REACHED_DESTINATION_RE.search(p.message)
        if not m:
            continue
        coordinate = (int(m.group("x")), int(m.group("y")))
        attr = waypoint_labels.get(coordinate)
        if attr is None:
            continue
        events.append(
            TaskEvent(
                coordinate=coordinate,
                timestamp=p.timestamp,
                module=p.module,
                function=p.function,
                line_no=p.line_no,
                raw_line=p.raw_line,
                phase_label=f"reached_{attr}",
                attr_tag=attr,
                bot_id=m.group("bot_id"),
                confidence=Confidence.HEURISTIC,
            )
        )
    return events
