"""RQ job functions for the batch (window) and full-scan modes.

Wired up structurally (queue name, connection, worker entrypoint) but the
actual scan-and-parse job bodies are intentionally left as TODOs - see
PLAN.md "Job/queueing model". `/api/window` and `/api/scan` in
api/routes.py currently return a job_id without enqueueing; wiring those
two call sites to `run_window_scan.delay(...)`/`run_full_scan.delay(...)`
here is the next piece of work, once the per-task-type resolvers beyond
relay_pps_task exist (a window/full scan needs to classify every task type
it finds, not just one).
"""

from __future__ import annotations

import os

import redis
from rq import Queue

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

redis_conn = redis.from_url(REDIS_URL)
queue = Queue("scans", connection=redis_conn)


def run_window_scan(butler_ip: str, ssh_user: str, from_iso: str, to_iso: str) -> dict:
    """TODO: implement per PLAN.md Mode 2 - find every task-creation marker
    in [from_iso, to_iso], build a TaskTrace per task (across all resolvers
    in parsers.task_types, falling back to parsers.correlation for types
    without a direct resolver), return the set + aggregate stats.
    """
    raise NotImplementedError("Window scan job body not yet implemented")


def run_full_scan(butler_ip: str, ssh_user: str, from_iso: str) -> dict:
    """TODO: implement per PLAN.md Mode 3 - same as run_window_scan but
    bounded only by `from_iso` (to "now"), respecting the hard cap already
    enforced in api/routes.py before this is ever enqueued.
    """
    raise NotImplementedError("Full scan job body not yet implemented")
