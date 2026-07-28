"""Fallback attribution for task types without a direct MainTaskKey on
movement lines (see task_types/__init__.py's KNOWN_UNIMPLEMENTED_TYPES).

Heuristic: an orphan movement line (bot_id + timestamp + attr, no
MainTaskKey) is attributed to the nearest known TaskTrace for that same
butler_id whose [created_at, completed_at] window (widened by
`window_seconds` on both ends, to allow for dispatch queueing delay - see
the ~3m39s queued gap observed in the real relay_pps_task trace) contains
the event's timestamp. Any event attributed this way is tagged
Confidence.HEURISTIC, never EXACT - the UI must visually distinguish
inferred attribution from log-certain data (see models.Confidence).

This is intentionally a simple nearest-enclosing-window match, not a
scoring/ranking model - if two known tasks' windows overlap for the same
bot (shouldn't normally happen since a bot executes one task at a time, but
malformed data is possible), the first match wins and a warning should be
surfaced by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_WINDOW_SECONDS = 300  # 5 min pad on each side of a known task's span


@dataclass
class OrphanEvent:
    timestamp: datetime
    bot_id: str
    attr: str | None
    raw_line: str


@dataclass
class KnownTaskWindow:
    task_id: str
    butler_id: str
    created_at: datetime
    completed_at: datetime | None


def attribute_orphan_events(
    orphans: list[OrphanEvent],
    known_windows: list[KnownTaskWindow],
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
) -> dict[int, str]:
    """Returns {index into `orphans` -> task_id} for every orphan that
    falls within some known task's (padded) window for the same bot.
    Orphans with no match are simply absent from the result - callers
    should surface these as "unattributable" rather than guessing further.
    """
    pad = timedelta(seconds=window_seconds)
    result: dict[int, str] = {}
    for idx, ev in enumerate(orphans):
        for known in known_windows:
            if known.butler_id != ev.bot_id:
                continue
            end = known.completed_at or known.created_at
            if (known.created_at - pad) <= ev.timestamp <= (end + pad):
                result[idx] = known.task_id
                break
    return result
