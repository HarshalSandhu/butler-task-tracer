"""RQ worker entrypoint - run via `python worker_entry.py` (see
docker-compose.yml's `worker` service).
"""

from rq import Worker

from app.jobs import queue, redis_conn

if __name__ == "__main__":
    worker = Worker([queue], connection=redis_conn)
    worker.work()
