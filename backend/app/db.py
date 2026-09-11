"""SQLite engine/session for the task-trace cache -- see PLAN.md
'Persistence/caching' and models.TaskTraceRow's own docstring for what gets
cached and why. `SQLITE_PATH` matches the env var docker-compose.yml
already sets for the api/worker services; defaults to a local file when
running outside docker (e.g. this repo's dev `uvicorn` invocation).
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base

SQLITE_PATH = os.environ.get("SQLITE_PATH", "./task_tracer.db")

engine = create_engine(
    f"sqlite:///{SQLITE_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)
