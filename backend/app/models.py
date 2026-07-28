"""Core data model for parsed task lifecycles.

See PLAN.md "Core data model" - TaskEvent/TaskTrace here are the in-memory
representation; SQLAlchemy ORM models for persistence live at the bottom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from sqlalchemy import JSON, Column, DateTime, Float, String
from sqlalchemy.orm import DeclarativeBase


class Confidence(str, Enum):
    """Whether an event's task attribution came directly from the log line
    (EXACT - the line itself carried MainTaskKey) or was inferred by the
    butler_id + time-window fallback heuristic (HEURISTIC) for task types
    that don't log MainTaskKey on movement lines. The UI must be able to
    show this distinction - see correlation.py.
    """

    EXACT = "exact"
    HEURISTIC = "heuristic"


class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


@dataclass
class TaskEvent:
    timestamp: datetime
    module: str
    function: str
    line_no: int
    raw_line: str
    phase_label: str | None = None
    attr_tag: str | None = None
    bot_id: str | None = None
    confidence: Confidence = Confidence.EXACT


@dataclass
class TaskTrace:
    request_id: str | None
    task_id: str | None
    task_type: str | None
    butler_id: str | None
    events: list[TaskEvent] = field(default_factory=list)
    status: TaskStatus = TaskStatus.INCOMPLETE
    created_at: datetime | None = None
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def total_duration_seconds(self) -> float | None:
        if self.created_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.created_at).total_seconds()

    @property
    def queued_duration_seconds(self) -> float | None:
        if self.created_at is None or self.dispatched_at is None:
            return None
        return (self.dispatched_at - self.created_at).total_seconds()

    def phase_durations(self) -> list[dict]:
        """One entry per MOVEMENT event (attr_tag set), giving the duration
        since the previous movement event. Non-movement events in between
        (fork height changes, tote load, pps_control - attr_tag is None)
        are intentionally skipped as `from`/`to` endpoints here: they're
        instantaneous actions, not a distinct physical location, so a
        "phase" is always attributed to the last known grid attribute, not
        to whichever event happens to sit immediately before it in the
        list. This mirrors the manual analysis done this session, where
        e.g. "relay_storable_io_point -> relay_storable" is one phase
        regardless of any tracing lines logged in between.
        """
        out = []
        prev: TaskEvent | None = None
        for ev in self.events:
            if ev.attr_tag is None:
                continue
            if prev is not None:
                out.append(
                    {
                        "from_attr": prev.attr_tag,
                        "to_attr": ev.attr_tag,
                        "phase_label": ev.phase_label,
                        "duration_seconds": (ev.timestamp - prev.timestamp).total_seconds(),
                        "confidence": ev.confidence.value,
                        "timestamp": ev.timestamp,
                    }
                )
            prev = ev
        return out


class Base(DeclarativeBase):
    pass


class TaskTraceRow(Base):
    """Persisted TaskTrace - see PLAN.md 'Persistence/caching'."""

    __tablename__ = "task_traces"

    task_id = Column(String, primary_key=True)
    request_id = Column(String, index=True, nullable=True)
    butler_ip = Column(String, index=True, nullable=False)
    task_type = Column(String, index=True, nullable=True)
    butler_id = Column(String, index=True, nullable=True)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_duration_seconds = Column(Float, nullable=True)
    events_json = Column(JSON, nullable=False)  # serialized list[TaskEvent]
    fetched_at = Column(DateTime, nullable=False)  # cache freshness marker


class ScanJobRow(Base):
    __tablename__ = "scan_jobs"

    job_id = Column(String, primary_key=True)
    butler_ip = Column(String, nullable=False)
    mode = Column(String, nullable=False)  # "task" | "window" | "scan"
    params_json = Column(JSON, nullable=False)
    status = Column(String, nullable=False)  # "queued" | "running" | "done" | "error"
    result_json = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
