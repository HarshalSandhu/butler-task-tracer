"""Per-task-type MainTaskKey resolution registry.

Only relay_pps_task has a confirmed, directly-resolvable movement-line
pattern (see relay_pps_task.py docstring - proven against a real trace this
session). Every other task type currently falls back to
`parsers.correlation` (butler_id + time-window heuristic) until real log
samples for those types are captured and a dedicated module is added here,
following the same shape as relay_pps_task.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import relay_pps_task

if TYPE_CHECKING:
    import types

REGISTRY: dict[str, "types.ModuleType"] = {
    relay_pps_task.TASK_TYPE: relay_pps_task,
}

# Task types known to exist (per PLAN.md's task-type survey) but without a
# dedicated resolver module yet - listed explicitly so it's obvious in code
# review what's missing, rather than silently falling through.
KNOWN_UNIMPLEMENTED_TYPES = frozenset(
    {
        "relay_group_task",
        "movetask",
        "chargetask",
        "bot_transport_task",
        "dummy_tote_relay_task",
        "rangergrouptask",
        "early_dispatch_task",
        "conveyor_move_task",
    }
)


def get_resolver(task_type: str):
    """Returns the task_types module for `task_type`, or None if it must
    fall back to the correlation heuristic.
    """
    return REGISTRY.get(task_type)
