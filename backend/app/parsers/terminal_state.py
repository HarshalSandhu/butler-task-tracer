"""Classifies a TaskTrace's final status: completed / failed / incomplete.

Confirmed markers this session:
  - Success terminal: "Delete Request with Task key ~p" (pgsql_adapter.erl)
    -- but this is the generic pgsql-layer marker, and does NOT fire for
    every task type's own real completion. Confirmed against two real,
    definitely-completed traces that this generic marker alone missed:

      * relay_pps_task: `relay_pps_subtasks:set_relay_pps_task_complete:
        ...Relay Pps task: <<"KEY">> complete, for HTM: ~p` -- logged
        right after `relay_pps_task:set_status: ...#relay_pps_task_delete:
        deleting relay_pps_task <<"KEY">> because status is complete`.
        Without this, a real relay_pps_task that unambiguously finished
        (per its own log) was reported "incomplete", with no
        total_duration_seconds, purely because the generic marker wasn't
        present in the grepped window.
      * relay_group_task: `The Current SubTask is : {subtask,
        set_relay_group_task_status,set_relay_group_task_status,
        [complete]}` -- the *executed* status transition (not the planned
        SubTask_list dump, which lists this as a future step regardless of
        whether it ever actually ran). Same module/function as the
        self-reschedule status lines task_types/relay_group_task.py
        already parses into a "group_status:*" event, but classify() never
        looked at those event semantics before this fix.
  - Failure markers (any one is enough to flag failed, absent a later
    success terminal): "Deassigning task: ~p for butler: ~p" (WARNING,
    deassign_task.erl:189), mnesia "{aborted, Reason}" transaction lines,
    and "Abandoning the current_subtask as there is new schedule with new
    task: ~p" (appears verbatim across bot_transport_subtasks.erl,
    rgt_subtasks.erl, dummy_tote_relay_subtasks.erl, relay_group_subtasks.erl)
    -- ***but only when the "new task" it names is a *different* task_id***.
    Verified against a real relay_group_task trace: a VTM batching several
    totes fires this exact line every time it reschedules itself onto its
    OWN next tote-leg (self-continuation, completely normal), which would
    otherwise flag every multi-tote relay_group_task as spuriously FAILED.
    Only treat it as a real failure signal when the named task differs from
    the one being classified -- i.e. something else genuinely preempted it.

A trace is never silently reported "completed" just because the scan window
ended - if neither a success nor failure terminal was observed, it's
"incomplete" (still running, or the log window was too narrow).
"""

from __future__ import annotations

import re

from app.models import TaskStatus

_SUCCESS_RE = re.compile(r'Delete Request with Task key\s+<<"[^"]+">>')
_RELAY_PPS_COMPLETE_RE = re.compile(r"Relay Pps task:\s*<<\"[^\"]+\">>\s*complete,\s*for HTM:")
_RELAY_GROUP_COMPLETE_RE = re.compile(
    r"The Current SubTask is\s*:\s*\{subtask,set_relay_group_task_status,"
    r"set_relay_group_task_status,\[complete\]\}"
)
_DEASSIGN_RE = re.compile(r"Deassigning task:\s*\S+\s*for butler:")
_ABORTED_RE = re.compile(r"\{aborted,")
_ABANDON_RE = re.compile(
    r"Abandoning the current_subtask as there is new schedule with new task:\s*(?P<target>.+)$"
)
# The real production form is an Erlang tuple, `{relay_group_task,<<"KEY">>}`;
# extract just the KEY for comparison. Anything that doesn't parse as that
# tuple shape (e.g. a plain opaque id) is compared as-is.
_TUPLE_TASK_ID_RE = re.compile(r'\{\w+,<<"(?P<task_id>[^"]+)">>\}')


def _abandon_target_id(raw_target: str) -> str:
    m = _TUPLE_TASK_ID_RE.search(raw_target)
    return m.group("task_id") if m else raw_target.strip()


def classify(messages: list[str], task_id: str | None = None) -> TaskStatus:
    """`messages` should be every matched log message (in any order) for
    the task being classified. `task_id` (optional, for backward
    compatibility with existing callers) lets the "Abandoning..." marker
    be judged correctly -- see module docstring; omitting it preserves the
    old unconditional-failure behavior for that one pattern.
    """
    has_success = any(
        _SUCCESS_RE.search(m) or _RELAY_PPS_COMPLETE_RE.search(m) or _RELAY_GROUP_COMPLETE_RE.search(m)
        for m in messages
    )

    has_failure = any(_DEASSIGN_RE.search(m) or _ABORTED_RE.search(m) for m in messages)
    if not has_failure:
        for m in messages:
            abandon = _ABANDON_RE.search(m)
            if not abandon:
                continue
            target_id = _abandon_target_id(abandon.group("target"))
            if task_id is None or target_id != task_id:
                has_failure = True
                break

    if has_success:
        return TaskStatus.COMPLETED
    if has_failure:
        return TaskStatus.FAILED
    return TaskStatus.INCOMPLETE
