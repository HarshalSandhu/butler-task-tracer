"""Bulk task discovery for the scan/list view (PLAN.md Mode 3, "Full Scan").

Unlike the single-task deep-dive (which greps by a known task_id), this
needs to find *every* relay_group_task/relay_pps_task inside a time window
without knowing any task_id up front. The anchor line that makes this cheap
for both task types at once (confirmed against the real validation VM):

    rm_subtasks:handle_start_task_cast:{336,6}: butler_id=<N> Starting
    TaskId: {<task_type>,<<"<task_id>">>}

This is a single grep pattern that gives task_id, task_type, and bot_id
directly for the FIRST bot to pick up a task, in one line, for every task
type dispatched through rm_subtasks (confirmed for both relay_group_task
and relay_pps_task; the "#Task created" line id_resolver.py relies on is
relay_pps_task-only and doesn't fire for relay_group_task at all -- this
line is what's used instead here).

"Relay position" (bot, where applicable) comes from the same
goto_barcode_completed movement line both task_types.py resolvers already
parse (`attr=<grid_attr>`) -- correlated to the most recently *started*
task on the same bot_id, since a bot only ever runs one task at a time.
This is a streaming, single-pass, time-ordered correlation (no per-task
grep needed), deliberately cheaper than the deep-dive's per-task grep so a
24h-wide bulk scan stays fast.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.parsers.line_parser import ParsedLine

TASK_SUMMARY_TYPES = ("relay_group_task", "relay_pps_task", "chargetask")

# Matches both anchor lines this module needs in one grep pass -- see
# ssh/executor.py's grep_task_summary_lines.
TASK_SUMMARY_GREP_PATTERN = r"Starting TaskId:|goto_barcode_completed:"

_START_RE = re.compile(
    r"butler_id=(?P<bot_id>\d+) Starting TaskId: "
    r'\{(?P<task_type>\w+),<<"(?P<task_id>[^"]+)">>\}'
)

# Same shape as task_types/relay_pps_task.py's _MOVEMENT_RE, but without the
# MainTaskKey requirement -- this module correlates by bot_id/time instead,
# since relay_group_task's movement lines don't always carry it either.
_MOVEMENT_RE = re.compile(
    r"goto_barcode_completed: bot (?P<bot_id>\d+) reached \{-?\d+,-?\d+\} "
    r"\(attr=(?P<attr>\w+)\)"
)


@dataclass
class TaskSummary:
    task_id: str
    task_type: str
    bot_id: str
    created_at: datetime
    relay_position: str | None = None
    last_seen_at: datetime | None = None
    is_bot_current_task: bool = True


def build_task_summaries(parsed: list[ParsedLine]) -> list[TaskSummary]:
    """`parsed` should be every line matching TASK_SUMMARY_GREP_PATTERN,
    across however many log files/rotations were searched -- order doesn't
    matter going in, this sorts by timestamp itself, since correlation only
    works correctly in chronological order (a movement line must attach to
    whichever task most recently started on that bot *before* it, not just
    any task on that bot).

    One "Starting TaskId" line per task_id is the common case, but a
    relay_group_task (VTM batching several totes) re-dispatches itself for
    each tote leg, re-emitting the *same* task_id's Starting line multiple
    times (confirmed against the real validation VM -- the terminal_state.py
    self-reschedule fix exists for the same reason). Deduping by task_id
    here keeps the scan list to one row per real task, not one per leg.
    """
    ordered = sorted(parsed, key=lambda p: p.timestamp)

    open_task_by_bot: dict[str, TaskSummary] = {}
    tasks_by_id: dict[str, TaskSummary] = {}
    all_tasks: list[TaskSummary] = []

    for p in ordered:
        start = _START_RE.search(p.message)
        if start is not None:
            bot_id = start.group("bot_id")
            task_id = start.group("task_id")
            existing = tasks_by_id.get(task_id)
            if existing is not None:
                # Same task re-dispatching on the same bot (self-reschedule
                # between legs) -- keep the one row, just re-mark it current.
                existing.is_bot_current_task = True
                open_task_by_bot[bot_id] = existing
                continue
            prior = open_task_by_bot.get(bot_id)
            if prior is not None:
                prior.is_bot_current_task = False
            summary = TaskSummary(
                task_id=task_id,
                task_type=start.group("task_type"),
                bot_id=bot_id,
                created_at=p.timestamp,
            )
            open_task_by_bot[bot_id] = summary
            tasks_by_id[task_id] = summary
            all_tasks.append(summary)
            continue

        movement = _MOVEMENT_RE.search(p.message)
        if movement is not None:
            bot_id = movement.group("bot_id")
            current = open_task_by_bot.get(bot_id)
            if current is not None and p.timestamp >= current.created_at:
                current.relay_position = movement.group("attr")
                current.last_seen_at = p.timestamp

    return all_tasks
