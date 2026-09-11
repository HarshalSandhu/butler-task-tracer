"""Per-task-type MainTaskKey resolution registry.

relay_pps_task and relay_group_task have confirmed, directly-resolvable
movement-line patterns (see each module's docstring - both proven against
real traces). Every other task type currently falls back to
`parsers.correlation` (butler_id + time-window heuristic) until real log
samples for those types are captured and a dedicated module is added here,
following the same shape as relay_pps_task.py / relay_group_task.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import chargetask, relay_group_task, relay_pps_task

if TYPE_CHECKING:
    import types

REGISTRY: dict[str, "types.ModuleType"] = {
    relay_pps_task.TASK_TYPE: relay_pps_task,
    relay_group_task.TASK_TYPE: relay_group_task,
    chargetask.TASK_TYPE: chargetask,
}

# Task types known to exist (per PLAN.md's task-type survey) but without a
# dedicated resolver module yet - listed explicitly so it's obvious in code
# review what's missing, rather than silently falling through.
KNOWN_UNIMPLEMENTED_TYPES = frozenset(
    {
        "movetask",
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
