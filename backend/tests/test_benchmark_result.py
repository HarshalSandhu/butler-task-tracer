"""Unit tests for the explicit, user-triggered benchmark-result save/view
endpoints (POST/GET /api/benchmark-result) -- see BenchmarkResultRow's own
docstring: never written automatically, only when the user clicks "Save
benchmark result" in TaskSwimlane.tsx, and history accumulates as separate
rows (same task_id can be saved more than once) rather than overwriting.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.routes as routes_module
from app.main import app
from app.models import Base

TASK_ID = "b55bbb47-6d71-4222-9085-d3e1006042ac"


@pytest.fixture()
def client(monkeypatch):
    # StaticPool (a single shared connection) is required here, not just
    # check_same_thread=False -- TestClient runs the ASGI app through
    # anyio's own worker thread, and sqlite's default per-thread pooling
    # would otherwise hand that thread a second, separate (and schema-less)
    # in-memory database instead of reusing this one.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    monkeypatch.setattr(routes_module, "SessionLocal", session_factory)
    return TestClient(app)


def _payload(**overrides):
    payload = {
        "task_id": TASK_ID,
        "task_type": "relay_pps_task",
        "butler_ip": "172.29.40.48",
        "thresholds": {"liftMaxSeconds": 5, "rotationMaxSeconds": 3, "forkMaxSeconds": 15},
        "results": [
            {"kind": "lift", "label": "lift 1", "duration_seconds": 2.0, "threshold_seconds": 5, "passed": True},
            {"kind": "lift", "label": "lift 2", "duration_seconds": 8.0, "threshold_seconds": 5, "passed": False},
            {
                "kind": "rotation",
                "label": "rotation 1",
                "duration_seconds": 1.0,
                "threshold_seconds": 3,
                "passed": True,
                "sequence_violation": True,
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_save_returns_pass_and_fail_counts(client):
    resp = client.post("/api/benchmark-result", json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    # 1 real pass (lift 1), 1 real fail (lift 2, over threshold), and the
    # "passed" rotation is still counted as a fail overall because of its
    # sequence_violation -- a benchmark result can't be a clean pass if
    # the lift-before-rotation ordering was violated, even if its own
    # duration was under threshold.
    assert body["pass_count"] == 1
    assert body["fail_count"] == 2
    assert "recorded_at" in body


def test_get_returns_saved_results_newest_first(client):
    client.post("/api/benchmark-result", json=_payload())
    client.post("/api/benchmark-result", json=_payload())

    resp = client.get(f"/api/benchmark-result/{TASK_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == TASK_ID
    assert len(body["results"]) == 2
    # newest first
    assert body["results"][0]["recorded_at"] >= body["results"][1]["recorded_at"]
    assert body["results"][0]["pass_count"] == 1
    assert body["results"][0]["fail_count"] == 2
    assert body["results"][0]["thresholds"] == {"liftMaxSeconds": 5, "rotationMaxSeconds": 3, "forkMaxSeconds": 15}
    assert len(body["results"][0]["results"]) == 3


def test_get_is_empty_for_a_task_that_was_never_saved(client):
    resp = client.get("/api/benchmark-result/never-saved-task-id")
    assert resp.status_code == 200
    assert resp.json() == {"task_id": "never-saved-task-id", "results": []}


def test_saving_the_same_task_twice_does_not_overwrite(client):
    client.post("/api/benchmark-result", json=_payload())
    client.post("/api/benchmark-result", json=_payload(thresholds={"liftMaxSeconds": 1, "rotationMaxSeconds": 1, "forkMaxSeconds": 1}))

    resp = client.get(f"/api/benchmark-result/{TASK_ID}")
    thresholds_seen = [r["thresholds"]["liftMaxSeconds"] for r in resp.json()["results"]]
    assert sorted(thresholds_seen) == [1, 5]
