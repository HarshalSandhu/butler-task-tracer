# Butler Task Lifecycle Tracer

A read-only observability tool for GreyOrange `butler_server` warehouse-robot task lifecycles.
Given a `butler_ip` and either a `task_id` or a time range, it SSHes into that VM, greps its MHS
debug logs, and reconstructs a task's full timeline (creation -> dispatch -> per-phase movement ->
completion) with durations between steps, plus aggregate distribution stats across many tasks.

## Scope: read-only, always

This tool only ever runs `grep`/`ls`/`zgrep` style read commands against remote log files over SSH.
It never sends commands to a live butler_server node's console, never restarts/stops anything, and
never mutates remote state. If you're looking for a way to control a bot or the running application,
this is not that tool - see `butler_server`'s own RMC/HTTP APIs for that (and be very careful with
those; a live Erlang console attach is not the same risk profile as this tool).

## SSH access model

This tool never accepts, stores, or transmits a private key. The only credentials it uses are
your own local `~/.ssh` keys, bind-mounted read-only into the containers exactly the way
`butler_server`'s own `.devcontainer/docker-compose.yml` and `dialyzer_run.sh` already do it -
passwordless publickey auth, `BatchMode=yes` so it fails fast instead of prompting for a password.
The API surface takes a `butler_ip` (and optional `ssh_user`, default `gor`) - nothing else.

## Running it

```bash
docker compose up
```

Frontend: http://localhost:5173
Backend API: http://localhost:8000/docs

## Project layout

- `backend/` - FastAPI + RQ + SQLite. See `backend/app/parsers/` for the log-parsing engine.
- `frontend/` - React + TypeScript + Vite. See `frontend/src/components/TaskSwimlane.tsx` for the
  main timeline visualization.
- `docker-compose.yml` - api / worker / redis services.

See `PLAN.md` for the full design rationale (parser ID-hierarchy handling, per-task-type
MainTaskKey resolution, failure detection, etc.) carried over from the original design session.
