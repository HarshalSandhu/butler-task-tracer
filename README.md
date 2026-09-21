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
git clone https://github.com/HarshalSandhu/butler-task-tracer.git
cd butler-task-tracer
```

### 1. Make sure the right SSH key is in `~/.ssh`

The containers bind-mount your own `~/.ssh` read-only (see "SSH access model" above) - they
never accept a key as input. If the key that has access to your target boxes isn't already
one of the default identity files ssh tries automatically, copy it into `~/.ssh` under its
own name and point `SSH_KEY_PATH` (in `docker-compose.yml`, under both the `api` and `worker`
services) at its path **inside the container** (always `/root/.ssh/<filename>`, regardless of
where it lives on your host):

```bash
# Example: you have a specific key at ~/Downloads/validation_vm_key that isn't your default
cp ~/Downloads/validation_vm_key ~/.ssh/butler_tracer_ed25519
chmod 600 ~/.ssh/butler_tracer_ed25519
```

Then in `docker-compose.yml`:
```yaml
      - SSH_KEY_PATH=/root/.ssh/butler_tracer_ed25519
```

If your default identity file (e.g. `~/.ssh/id_ed25519`) already has access to the target
boxes, skip this step entirely - remove or leave blank the `SSH_KEY_PATH` line and ssh will
fall back to its normal identity-file resolution.

### 2. Bring it up

```bash
docker compose up --build
```

Frontend: http://localhost:5175
Backend API: http://localhost:8001/docs

(Ports are remapped from the defaults in this repo's `docker-compose.yml` - `8000`/`5173`
were already taken by another local project. Change the left side of each `ports:` mapping,
and the frontend's `VITE_API_BASE_URL`, if you need different ports on your machine.)

### 3. Run it natively without Docker (local dev / fallback)

If Docker isn't working on your machine (or you prefer plain local processes), the whole
stack runs as three local processes against a local Redis. This is also the fastest path
for iterating on the frontend/backend.

#### Prerequisites

| Tool | Version | Check it's installed with |
| --- | --- | --- |
| Python | 3.11+ (project declares >=3.12; ships with a 3.11 venv) | `python3.11 --version` |
| Node.js + npm | Node 20+ (tested with 25) | `node --version && npm --version` |
| Redis | 7.x (any modern version works) | `redis-cli ping` -> `PONG` |
| OpenSSH client | any | `which ssh` |
| SSH keys to target butler boxes | your normal `~/.ssh` identity | `ssh -o BatchMode=yes <user>@<butler_ip> true` |
| Free ports | `8010` (API) and `5173` (frontend) | `lsof -nP -iTCP:8010 -sTCP:LISTEN` |

Notes:
- Redis must be running locally first: `brew install redis && brew services start redis`
  (Homebrew/macOS) or `redis-server --daemonize yes` (any OS).
- Natively, ssh resolves auth from your **default** `~/.ssh` identity files exactly like a
  terminal (no `SSH_KEY_PATH` needed). If you need a *specific* non-default key, set
  `SSH_KEY_PATH=/absolute/path/to/your_key` in the backend/worker shells below - the
  executor (backend/app/ssh/executor.py) only uses it as an extra `-i` argument, never as
  a stored secret.
- If `8010`/`5173` are busy, pick different ports and update `VITE_API_BASE_URL` in
  `frontend/.env.local` to match.

#### 3a. Backend API (terminal 1)

```bash
cd backend
# First time only - create the venv and install (uses the existing .venv311 otherwise):
python3.11 -m venv .venv311   # skip if it already exists
./.venv311/bin/pip install -e .
# Run it:
REDIS_URL=redis://localhost:6379/0 SQLITE_PATH=$PWD/task_tracer.db \
  ./.venv311/bin/uvicorn app.main:app --host 0.0.0.0 --port 8010
```

Verify: `curl http://localhost:8010/health` -> `{"status":"ok"}`, API docs at
http://localhost:8010/docs

#### 3b. RQ worker (terminal 2)

```bash
cd backend
REDIS_URL=redis://localhost:6379/0 SQLITE_PATH=$PWD/task_tracer.db \
  ./.venv311/bin/python worker_entry.py
```

Verify the log line `*** Listening on scans...` appears (the queue is named `scans`).

#### 3c. Frontend (terminal 3)

```bash
cd frontend
npm install                    # first time only
# Point the app at the local API (8010 is NOT the docker default, so set it):
echo "VITE_API_BASE_URL=http://localhost:8010" > .env.local
npm run dev -- --port 5173 --strictPort
```

`--port 5173` overrides the config's hardcoded `5175` (used only when running under
Docker), `--strictPort` fails fast instead of silently climbing to another port.

Verify: http://localhost:5173 (trace a task via SearchBar), and the whole view has
`Excel` / `Download all logs` / `HTML` export buttons.

## Project layout

- `backend/` - FastAPI + RQ + SQLite. See `backend/app/parsers/` for the log-parsing engine.
- `frontend/` - React + TypeScript + Vite. See `frontend/src/components/TaskSwimlane.tsx` for the
  main timeline visualization.
- `docker-compose.yml` - api / worker / redis services.

See `PLAN.md` for the full design rationale (parser ID-hierarchy handling, per-task-type
MainTaskKey resolution, failure detection, etc.) carried over from the original design session.
