# Butler Task Lifecycle Tracer — New Standalone Tool

## Context

Over this session we manually reconstructed a warehouse robot task's full lifecycle (creation → dispatch → per-phase movement → completion) by hand: SSH into a validation VM, grep MHS `debug.log` for a task ID, and compute durations between consecutive log lines. It worked and produced real, useful numbers (e.g. a `relay_pps_task` with an outbound relay-storable↔IO-point leg of 7.93s matching its return leg at 8.01s). But it's fully manual, doesn't scale past one task at a time, and can't produce the kind of aggregate/distribution stats (avg/p95 per phase) that this whole investigation has been chasing since the start of the session — the InfluxDB queries we built earlier only work for phases that already have a pre-computed `time_diff` field (conveyor events); most of what's actually being tested (relay↔storable, charger↔charger_reinit, PPS legs, rotations) has no such field and can only come from log reconstruction.

The goal: turn that manual process into a real internal tool — a web UI where anyone enters a target VM's IP, and either looks up one task's full timeline, or gets an aggregate view across a time window, sourced from live SSH log greps against the actual butler_server debug logs. This also needs to close the credential-hygiene gap from earlier in the session (a raw private key was pasted into chat) by construction — the tool must never accept, store, or transmit a private key at all.

We also discovered a real distributed tracing backend already exists (Elastic APM/Elasticsearch/Kibana, receiving `task.key`-tagged spans from `gm_trace`), but it's capped at 10% root sampling — not reliable enough to be the primary data source, so this tool is log-grep-based, full stop, for v1.

## Decisions (confirmed with user)

- New standalone repo, fully decoupled from `butler_server`, Dockerized.
- SSH access: bind-mount the operator's own `~/.ssh` read-only into the containers — same convention as `butler_server/.devcontainer/docker-compose.yml:12` (`./.ssh:/home/codespace/.ssh:cached`) and `butler_server/dialyzer_run.sh` (passwordless publickey auth, user `gor` by default). The tool's API surface never accepts a private key as a parameter, upload, or config value — only `butler_ip` (+ optional `ssh_user`).
- v1 feature scope: core single-task timeline view + batch/aggregate view, **plus** anomaly flagging (vs. historical p50/p95 baseline) and side-by-side task comparison. Live-tailing and warehouse-map replay animation are explicitly deferred to a future v2 — not built now.
- Stack: Python 3.12 + FastAPI backend, React + TypeScript frontend. Boring, fast-to-ship, easy to maintain by a small team.

## Architecture

### Backend (`backend/`)

**Stack**: FastAPI + Uvicorn, RQ (Redis Queue) for background jobs, SQLite (SQLAlchemy, WAL mode) for persistence. Shell out to the real `ssh` binary via `subprocess` (not a pure-Python SSH client) so it transparently uses the operator's existing `~/.ssh/config`/known_hosts/agent resolution — `ssh -o BatchMode=yes -o ConnectTimeout=5 <user>@<ip> "<remote command>"`. `BatchMode=yes` fails fast with a clear error if passwordless key auth isn't set up for that IP, instead of hanging on a password prompt.

**Log discovery**: a single remote round-trip lists candidate debug.log paths + rotation files + mtimes (`ls -t /var/log/butler_server/log/mhs/debug.log* 2>/dev/null`, extensible to other install paths), letting the tool pick which rotated files are worth grepping based on mtime overlap with any given time range.

**Remote search**: everything happens server-side over one piped SSH command per query, streamed line-by-line into the parser — never buffering multi-GB files locally, never copying them over the network. Confirmed pattern from this session: `ssh user@ip "grep '<id>' /var/log/butler_server/log/mhs/debug.log{,.0,.1,...,.bkp} 2>/dev/null"`.

**ID resolution (two-hop, not an edge case)**: `RequestId` is logged at task-request time (`transport_request_event_handler.erl:554`, `"#Triggered task creation: RequestId ~p"`); the real `TaskId`/`MainTaskKey` only appears once storage completes (`"#transport_request: sent for storing task ~p"`, ~line 2910) and is *not* co-logged with the RequestId on the same line. The parser must grep RequestId first, extract the real TaskId from the surrounding lines, then re-grep by TaskId — exactly what we did by hand this session.

**Per-task-type MainTaskKey resolution**: the "goto_barcode_completed" movement line (`rm_common_subtasks.erl`, `"goto_barcode_completed: bot ~p reached ~p (attr=~p), Task=..., MainTaskKey=~p"`) only resolves MainTaskKey correctly for `{relay_pps_task, TaskKey}`. Other task types (`relay_group_task`, `movetask`, `chargetask`, `bot_transport_task`, `dummy_tote_relay_task`, `rangergrouptask`, `early_dispatch_task`, `conveyor_move_task`) log `MainTaskKey=undefined` on this line even though bot/coordinate/attr are always present. Backend needs a per-type key-resolution registry (`parsers/task_types/*.py`, one module per type mirroring the Erlang `get_main_task_key/1` split across `relay_pps_task.erl`/`conveyor_move_task.erl`/`tote_move_task.erl`/`port_move_task.erl`), plus a fallback correlation heuristic for types where it's genuinely absent: attribute orphan movement lines to the nearest enclosing known task for that `butler_id` within a bounded time window, tagging those events `confidence="heuristic"` (vs. `"exact"`) so the UI can visually distinguish inferred attribution from log-certain data.

**Failure/incomplete detection**: a trace is `status="failed"` if it contains a deassign/abandon marker (`"Deassigning task: ~p for butler: ~p"`, `"Abandoning the current_subtask as there is new schedule with new task: ~p"`, mnesia `{aborted, Reason}`) without a terminal success marker (`"Delete Request with Task key ~p"`, `pgsql_adapter.erl`); `status="incomplete"` if neither appears by the end of the scan window. Never silently reported as complete.

**Core data model**: `TaskEvent {timestamp, module, function, line_no, raw_line, phase_label, attr_tag, bot_id, confidence}`, `TaskTrace {request_id, task_id, task_type, butler_id, events: [TaskEvent], status, created_at, dispatched_at, completed_at, total_duration}`.

**Two operating modes + a bounded third**:
1. `task_id` given → single `TaskTrace`, returned synchronously if the grep resolves quickly (~seconds), else falls back to a background job with a `job_id` to poll.
2. Time range given (no `task_id`) → background job: find every task creation marker in-window (per task type), build a `TaskTrace` for each, return the set + aggregate stats (mean/p50/p95 per phase+attr, split by scenario the way the earlier InfluxDB query was — e.g. tote-on-fork vs. going-to-load).
3. Neither given → **do not implement true unbounded**. Default to a "last 24h" scan; widening beyond that (up to a hard cap, e.g. 30 days) requires explicit user confirmation in the UI and is still capped server-side regardless of what the request asks for.

**Persistence/caching**: SQLite tables `task_traces` (one row per resolved trace — JSON event blob + queryable scalar columns) and `scan_jobs`. Before launching a new SSH scan, check for a fresh existing row (task_id match, or overlapping time range + same `butler_ip`, within a TTL — logs are append-only so old fully-captured entries never change) and skip re-scanning if still fresh. This also means the aggregate/distribution view accumulates history for free across repeated runs — query `task_traces` directly for percentiles instead of re-parsing logs every time.

**Docker composition**: `api` (FastAPI/Uvicorn, mounts `~/.ssh:ro` + shared SQLite volume), `worker` (RQ worker, same image, mounts the same), `redis` (job queue, ephemeral). Optional `rq-dashboard` for job visibility.

### Frontend (`frontend/`)

**Stack**: React + TypeScript + Vite, Tailwind CSS, Recharts for charts (D3 scoped only to the swimlane/compare rendering if Recharts' bar approach proves limiting), TanStack Query for API polling (handles the "long-running SSH grep" loading pattern), React Router for URL-driven navigation.

**Screens**:
- Persistent top bar: `butler_ip` combobox (with a small recently-used list), mode selector (Task Deep-Dive / Batch-Window / Full Scan), task_id field with autocomplete + "recent tasks" dropdown, time-range picker (relative presets + custom), one "Run Analysis" button. Submitting produces a shareable URL immediately, before results load.
- **Single-task deep-dive**: stat strip (task_id, type, total duration, key timestamps) → horizontal Gantt/swimlane (one row per phase, bar length = duration, color keyed by `attr_tag` since that mapping already exists in the data) with non-movement subtask actions (fork height changes, tote load, pps_control) rendered as diamond markers on a thin events row below → collapsible raw-log-line table underneath (always show the source lines that produced the visualization).
- **Batch/aggregate view**: summary stats row, per-phase histogram/box-plot (split by scenario via legend toggle, overlaid p50/p95), sortable task table (task_id, type, total time, anomaly flag) where every row links into the deep-dive view.
- **Full Scan**: same as batch view but defaults to last 24h with a visible, explicit "widen" control requiring a second confirmation click and an estimated-cost warning, per the backend's hard cap.
- **Compare view**: two task_ids (or a task vs. baseline) rendered as stacked swimlanes on a shared, phase-start-normalized (not wall-clock) x-axis, with a diff strip.

**Anomaly flagging**: compute rolling p50/p95 per phase+attr from `task_traces`, flag any phase exceeding 2x p95 directly on the deep-dive Gantt bar (red outline + "3.1x p95" badge) and as a filterable column in the batch table.

**URL structure** (shareable/bookmarkable):
- `/trace/:butler_ip/task/:task_id`
- `/trace/:butler_ip/window?from=...&to=...`
- `/trace/:butler_ip/scan?from=...&to=...`
- `/trace/:butler_ip/compare?a=:task_id&b=:task_id`

## Critical files to create

Backend:
- `backend/app/ssh/executor.py` — subprocess SSH wrapper enforcing `BatchMode=yes` + the no-key-acceptance invariant
- `backend/app/parsers/line_parser.py` — single compiled regex for the lager log format (`YYYY-MM-DD HH:MM:SS.mmm [level][pid] --- module:function:line: message`, confirmed universal across severities)
- `backend/app/parsers/id_resolver.py` — RequestId → TaskId two-hop resolution
- `backend/app/parsers/task_types/*.py` — per-task-type MainTaskKey resolution registry (relay_pps_task, relay_group_task, movetask, chargetask, bot_transport_task, dummy_tote_relay_task, rangergrouptask, early_dispatch_task, conveyor_move_task)
- `backend/app/parsers/correlation.py` — butler_id + time-window fallback heuristic for types lacking a direct MainTaskKey
- `backend/app/parsers/terminal_state.py` — failed/incomplete/completed classification
- `backend/app/models.py` — `TaskEvent`/`TaskTrace` + SQLAlchemy `task_traces`/`scan_jobs` tables
- `backend/app/api/routes.py` — the 3-mode endpoint surface + job polling
- `docker-compose.yml` — api/worker/redis composition, `~/.ssh:ro` mounts

Frontend:
- `frontend/src/App.tsx` — routing shell
- `frontend/src/components/TaskSwimlane.tsx` — Gantt/swimlane + event markers, color-by-attr
- `frontend/src/components/PhaseDistribution.tsx` — per-phase histogram/box-plot, scenario split
- `frontend/src/components/CompareView.tsx` — two-trace normalized overlay
- `frontend/src/hooks/useTaskTrace.ts` — TanStack Query hook wrapping the backend API, handles poll/loading states
- `frontend/src/lib/anomaly.ts` — p50/p95 baseline + flagging logic shared across views

## Reference material from this session (ground truth for parser correctness)

- Real traced example (`5fbc8f16-3593-48d2-a7ac-c7cb3826949b`, a `relay_pps_task` on butler 200): full phase list with measured durations, saved conceptually in this plan's Context section — use as the first fixture/test case for the parser.
- Relay pair mapping (`relay_storable` ↔ `relay_storable_io_point`, 28 pairs, derived from `map.json`'s `adjacency` field) — useful for phase-labeling/validating relay legs in the UI.
- `apps/mhs/src/interfaces/in/transport_request_event_handler.erl`, `apps/mhs/src/fleet/butler/rm_common_subtasks.erl`, `apps/mhs/src/fleet/butler/rm_move_subtasks.erl`, `apps/mhs/src/fleet/task/deassign_task.erl`, `apps/butler_base/src/critical/gm_lager.erl` (log format source) — primary references for the parser's regex/marker set.

## Verification

1. **Backend unit tests**: feed the parser fixed sample log excerpts (including the real `5fbc8f16...` trace captured this session) and assert the reconstructed `TaskTrace` matches the manually-computed durations (7.93s/8.01s relay legs, etc.) exactly.
2. **End-to-end against the real validation VM**: run the dockerized tool locally, point it at the same `butler_ip` used this session, look up a known real `task_id`, and confirm the UI's computed total duration and phase breakdown matches this session's manual trace.
3. **Batch mode**: run a time-range query spanning several known tasks, confirm the aggregate stats (mean/p95 per phase) are directionally consistent with the InfluxDB relay-hop query built earlier (18-22s range for io↔storable).
4. **Failure-path test**: manually deassign/abandon a task on the validation VM (or use a known historical example if available) and confirm the tool correctly flags it `status="failed"` rather than `"completed"` or silently omitting it.
5. **SSH safety check**: confirm the tool's API rejects any request attempting to pass key material, and confirm `BatchMode=yes` produces a clear, immediate error (not a hang) against an IP without passwordless auth configured.
