"""Classifies a TaskTrace's final status: completed / failed / incomplete.

Confirmed markers this session:
  - Success terminal: "Delete Request with Task key ~p" (pgsql_adapter.erl)
  - Failure markers (any one is enough to flag failed, absent a later
    success terminal): "Deassigning task: ~p for butler: ~p" (WARNING,
    deassign_task.erl:189), "Abandoning the current_subtask as there is new
    schedule with new task: ~p" (appears verbatim across
    bot_transport_subtasks.erl, rgt_subtasks.erl, dummy_tote_relay_subtasks.erl,
    relay_group_subtasks.erl), mnesia "{aborted, Reason}" transaction lines.

A trace is never silently reported "completed" just because the scan window
ended - if neither a success nor failure terminal was observed, it's
"incomplete" (still running, or the log window was too narrow).
"""

from __future__ import annotations

import re

from app.models import TaskStatus

_SUCCESS_RE = re.compile(r'Delete Request with Task key\s+<<"[^"]+">>')
_FAILURE_PATTERNS = [
    re.compile(r"Deassigning task:\s*\S+\s*for butler:"),
    re.compile(r"Abandoning the current_subtask as there is new schedule with new task:"),
    re.compile(r"\{aborted,"),
]


def classify(messages: list[str]) -> TaskStatus:
    """`messages` should be every matched log message (in any order) for
    the task being classified.
    """
    has_success = any(_SUCCESS_RE.search(m) for m in messages)
    has_failure = any(p.search(m) for m in messages for p in _FAILURE_PATTERNS)

    if has_success:
        return TaskStatus.COMPLETED
    if has_failure:
        return TaskStatus.FAILED
    return TaskStatus.INCOMPLETE
