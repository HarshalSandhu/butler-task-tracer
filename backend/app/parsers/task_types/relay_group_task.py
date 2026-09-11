"""MainTaskKey resolution for relay_group_task.

Confirmed against a real trace: unlike relay_pps_task, the
"goto_barcode_completed" movement line for this task type logs
`MainTaskKey=undefined` -- but the *same line*'s `Task=` field already
carries the real key directly:

    "goto_barcode_completed: bot 214 reached {11,51} (attr=ttp_storable_io_point),
     Task={relay_group_task,<<"87510814-d3da-465b-9a90-4e358056e293">>}, MainTaskKey=undefined"

So this is not the correlation.py heuristic case PLAN.md originally
flagged it as -- the key is log-certain (Confidence.EXACT), it's just in a
different field than relay_pps_task's. `parse_movement` reads it from
`Task=` instead of `MainTaskKey=`.

relay_group_task also carries multi-tote batch state via its own
`{subtask,set_relay_group_task_status,set_relay_group_task_status,[STATUS]}`
tracing lines (STATUS one of: loading_from_relay, loading_from_storable,
unloading_at_relay, unloading_at_storable, complete) -- these are the VTM's
own phase markers, exposed here the same way relay_pps_task exposes its
"Tracing <event>" lines, so the frontend's non-movement-event rendering
picks them up without special-casing this task type.
"""

from __future__ import annotations

import re

TASK_TYPE = "relay_group_task"

_MOVEMENT_RE = re.compile(
    r"goto_barcode_completed: bot (?P<bot_id>\d+) reached \{(?P<x>-?\d+),(?P<y>-?\d+)\} "
    r'\(attr=(?P<attr>\w+)\), Task=\{relay_group_task,<<"(?P<main_task_key>[^"]+)">>\}'
)


def resolve_main_task_key(line_message: str) -> str | None:
    m = _MOVEMENT_RE.search(line_message)
    return m.group("main_task_key") if m else None


def parse_movement(line_message: str) -> dict | None:
    """Full structured parse of a goto_barcode_completed message for this
    task type. Note MainTaskKey itself is not read here (it's literally
    "undefined" on this line for relay_group_task) -- the real key comes
    from `Task=` instead, which this regex captures as `main_task_key` for
    parity with relay_pps_task's dict shape.
    """
    m = _MOVEMENT_RE.search(line_message)
    if not m:
        return None
    return {
        "bot_id": m.group("bot_id"),
        "coordinate": (int(m.group("x")), int(m.group("y"))),
        "attr": m.group("attr"),
        "main_task_key": m.group("main_task_key"),
    }


_GROUP_STATUS_RE = re.compile(
    r"The Current SubTask is : \{subtask,set_relay_group_task_status,"
    r"set_relay_group_task_status,\[(?P<status>\w+)\]\}"
)

# Same "Tracing <event> event spanName=..., MainTaskKey=..." shape
# relay_pps_task uses, for the load/unload/fork-height/etc. subtasks a VTM
# also runs -- reused verbatim (including relay_pps_task.py's existing
# restriction to a *quoted* MainTaskKey, not "undefined") so both task types
# share one rendering path for non-movement events on the frontend.
_TRACING_RE = re.compile(
    r'Tracing (?:event )?(?P<event_name>\w+)(?: event)? spanName\s*=\s*'
    r'(?:<<"(?P<span_name>[^"]*)">>|undefined),\s*MainTaskKey\s*=\s*<<"(?P<main_task_key>[^"]+)">>'
)


def parse_tracing_event(line_message: str) -> dict | None:
    """Non-movement relay_group_task actions: either a group-status phase
    transition (loading_from_relay / unloading_at_storable / ... / complete)
    or a shared "Tracing X event" line (fork height, load_tote, etc.)."""
    m = _GROUP_STATUS_RE.search(line_message)
    if m:
        return {"event_name": f"group_status:{m.group('status')}", "span_name": None, "main_task_key": None}

    m = _TRACING_RE.search(line_message)
    if not m:
        return None
    return {
        "event_name": m.group("event_name"),
        "span_name": m.group("span_name"),
        "main_task_key": m.group("main_task_key"),
    }
