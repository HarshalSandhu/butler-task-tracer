"""MainTaskKey resolution for chargetask.

Confirmed against a real trace (001d1a82-f75f-4c1d-9568-2dd5ba33ecfb, bot
206): same shape as relay_group_task -- `MainTaskKey=undefined` on the
movement line, but `Task=` carries the real key directly:

    "goto_barcode_completed: bot 206 reached {506,506} (attr=charger_reinit),
     Task={chargetask,<<"001d1a82-f75f-4c1d-9568-2dd5ba33ecfb">>}, MainTaskKey=undefined"

Two distinct grid waypoints observed, both real attr values (not invented):
`charger_reinit` (the approach/staging point a bot reaches before docking --
also the point it backs out to before returning) and `charger` (the actual
charging dock). There is no dedicated "parking" attr -- confirmed against
the same real trace: the task's own final `goto_parking_point` subtask
actually lands the bot back at ordinary `relay_storable_io_point`/
`relay_storable` waypoints, reusing relay infrastructure rather than a
distinct parking zone.

The task's own lifecycle status (`pending,assigned` -> `pending,started` ->
`reached_reinit_point` -> `charging_started` -> `charging_complete`) is
logged separately by `chargetaskrec:set_task_status` -- see
parsers/charge_timing.py for how those lines are turned into the actual
charge-time breakdown (this module only resolves movement/MainTaskKey,
same division of labor as relay_group_task.py).
"""

from __future__ import annotations

import re

TASK_TYPE = "chargetask"

_MOVEMENT_RE = re.compile(
    r"goto_barcode_completed: bot (?P<bot_id>\d+) reached \{(?P<x>-?\d+),(?P<y>-?\d+)\} "
    r'\(attr=(?P<attr>\w+)\), Task=\{chargetask,<<"(?P<main_task_key>[^"]+)">>\}'
)


def resolve_main_task_key(line_message: str) -> str | None:
    m = _MOVEMENT_RE.search(line_message)
    return m.group("main_task_key") if m else None


def parse_movement(line_message: str) -> dict | None:
    m = _MOVEMENT_RE.search(line_message)
    if not m:
        return None
    return {
        "bot_id": m.group("bot_id"),
        "coordinate": (int(m.group("x")), int(m.group("y"))),
        "attr": m.group("attr"),
        "main_task_key": m.group("main_task_key"),
    }


# chargetask doesn't use the "Tracing <event> event spanName=..." shape the
# relay task types share -- its own status transitions are handled
# separately by charge_timing.py, not rendered as generic non-movement
# events, so this always returns None (no dedicated tracing-event line to
# parse for this task type).
def parse_tracing_event(line_message: str) -> dict | None:
    return None
