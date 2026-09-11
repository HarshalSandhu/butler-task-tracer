"""Unit tests for the local trace cache (TaskTraceRow + api/routes.py's
_load_cached_trace/_maybe_cache_trace) -- the point of this cache is to
skip SSH entirely on a hit, using real fixtures (relay_pps_task_70f0fa18.log
+ lift_telemetry_70f0fa18.log, the same pair test_fork_adjustment_events.py
and test_trace_builder_70f0fa18.py already validate against) so a round
trip through the cache is checked against known-real numbers, not just
"it returns something".
"""

from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.routes as routes_module
from app.models import Base, TaskStatus, TaskTraceRow

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
TASK_LINES = (FIXTURES / "relay_pps_task_70f0fa18.log").read_text().splitlines(keepends=True)
LIFT_ROTATION_LINES = (FIXTURES / "lift_telemetry_70f0fa18.log").read_text().splitlines()
TASK_ID = "70f0fa18-c9d9-4992-b209-0225654bf05f"
BUTLER_IP = "172.29.40.48"


@pytest.fixture()
def cache_db(monkeypatch):
    """A fresh in-memory sqlite per test, swapped in for the real
    module-level SessionLocal so these tests never touch the real cache
    file on disk."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(routes_module, "SessionLocal", session_factory)
    return session_factory


class _FakeNonTerminalTrace:
    status = TaskStatus.RUNNING
    butler_id = "210"
    created_at = None
    dispatched_at = None
    completed_at = None
    total_duration_seconds = None


def test_maybe_cache_trace_skips_non_terminal_status(cache_db):
    routes_module._maybe_cache_trace(
        BUTLER_IP, "some-running-task", None, "relay_pps_task", _FakeNonTerminalTrace(), ["line"], [], []
    )
    with cache_db() as session:
        assert session.get(TaskTraceRow, "some-running-task") is None


def test_load_cached_trace_is_none_on_a_genuine_miss(cache_db):
    assert routes_module._load_cached_trace(BUTLER_IP, "never-cached-task-id") is None


def test_load_cached_trace_is_none_when_butler_ip_does_not_match(cache_db):
    trace = routes_module._build_trace(TASK_ID, "relay_pps_task", None, TASK_LINES)
    routes_module._maybe_cache_trace(BUTLER_IP, TASK_ID, None, "relay_pps_task", trace, TASK_LINES, [], [])
    assert routes_module._load_cached_trace("10.0.0.99", TASK_ID) is None


def test_write_through_then_cache_hit_round_trip_matches_a_live_build(cache_db):
    # Build once the "live" way (exactly what the SSH path would produce),
    # cache it, then load it back purely from the cache -- the two
    # _trace_to_dict() outputs must be identical, since a cache hit is
    # supposed to be indistinguishable from a fresh fetch.
    live_trace = routes_module._build_trace(TASK_ID, "relay_pps_task", None, TASK_LINES)
    routes_module._apply_lift_rotation_lines(live_trace, TASK_LINES, LIFT_ROTATION_LINES, LIFT_ROTATION_LINES)
    assert live_trace.status == TaskStatus.COMPLETED  # sanity: this fixture is a real completed task

    routes_module._maybe_cache_trace(
        BUTLER_IP, TASK_ID, None, "relay_pps_task", live_trace, TASK_LINES, LIFT_ROTATION_LINES, LIFT_ROTATION_LINES
    )

    live_dict = routes_module._trace_to_dict(live_trace)
    cached_dict = routes_module._load_cached_trace(BUTLER_IP, TASK_ID)

    assert cached_dict is not None
    assert cached_dict == live_dict
    # And a concrete, known-real number (not just dict equality) --
    # test_fork_adjustment_events.py proves this fixture yields 4 fork
    # adjustments; the cached round trip must reproduce the same count.
    assert len(cached_dict["fork_adjustment_events"]) == 4


def test_cache_hit_avoids_rebuilding_charge_timing_incorrectly_for_non_chargetask(cache_db):
    # charge_timing must stay None for a relay_pps_task both live and cached.
    live_trace = routes_module._build_trace(TASK_ID, "relay_pps_task", None, TASK_LINES)
    routes_module._maybe_cache_trace(BUTLER_IP, TASK_ID, None, "relay_pps_task", live_trace, TASK_LINES, [], [])
    cached_dict = routes_module._load_cached_trace(BUTLER_IP, TASK_ID)
    assert cached_dict["charge_timing"] is None
