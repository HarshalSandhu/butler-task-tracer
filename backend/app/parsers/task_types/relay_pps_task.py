"""MainTaskKey resolution for relay_pps_task.

Confirmed this session: the "goto_barcode_completed" movement line directly
carries MainTaskKey for this task type:

    "goto_barcode_completed: bot ~p reached ~p (attr=~p), Task=..., MainTaskKey=~p"
    (rm_common_subtasks.erl:929)

This is the ONLY task type where PLAN.md's research confirmed direct
resolution on that line - see correlation.py for the fallback used by every
other task type.
"""

from __future__ import annotations

import re

TASK_TYPE = "relay_pps_task"

_MOVEMENT_RE = re.compile(
    r"goto_barcode_completed: bot (?P<bot_id>\d+) reached \{(?P<x>-?\d+),(?P<y>-?\d+)\} "
    r'\(attr=(?P<attr>\w+)\), Task=\{[^,]+,<<"[^"]*">>\}, MainTaskKey=<<"(?P<main_task_key>[^"]+)">>'
)


def resolve_main_task_key(line_message: str) -> str | None:
    """Extracts MainTaskKey from a single goto_barcode_completed message,
    if the line matches. Returns None otherwise (not this task type, or a
    non-movement subtask-tracing line - see the separate _TRACING_RE match
    used by the caller for those).
    """
    m = _MOVEMENT_RE.search(line_message)
    return m.group("main_task_key") if m else None


def parse_movement(line_message: str) -> dict | None:
    """Full structured parse of a goto_barcode_completed line: bot_id,
    coordinate, grid attribute (the phase label), and MainTaskKey.
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


_TRACING_RE = re.compile(
    r'Tracing (?:event )?(?P<event_name>\w+)(?: event)? spanName\s*=\s*'
    r'(?:<<"(?P<span_name>[^"]*)">>|undefined),\s*MainTaskKey\s*=\s*<<"(?P<main_task_key>[^"]+)">>'
)


def parse_tracing_event(line_message: str) -> dict | None:
    """Non-movement subtask actions (fork height changes, tote load,
    pps_control, etc.) are logged as "Tracing <event> event spanName=...,
    MainTaskKey = ..." lines - these are instantaneous actions, not
    movement legs, and should render as event markers, not Gantt bars.
    """
    m = _TRACING_RE.search(line_message)
    if not m:
        return None
    return {
        "event_name": m.group("event_name"),
        "span_name": m.group("span_name"),
        "main_task_key": m.group("main_task_key"),
    }
