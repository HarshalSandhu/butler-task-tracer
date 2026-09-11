/**
 * Thin client for the backend API (see backend/app/api/routes.py).
 * Note what this module has no field for: a private key / passphrase.
 * The only credential-adjacent inputs anywhere in this app are
 * `butlerIp` and `sshUser` - see README.md "SSH access model".
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type Confidence = 'exact' | 'heuristic'
export type TaskStatus = 'running' | 'completed' | 'failed' | 'incomplete'

export interface TaskEventDto {
  timestamp: string
  module: string
  function: string
  phase_label: string | null
  attr_tag: string | null
  bot_id: string | null
  confidence: Confidence
  raw_line: string
}

export interface PhaseDto {
  from_attr: string | null
  to_attr: string
  phase_label: string | null
  duration_seconds: number
  confidence: Confidence
  timestamp: string
  // Real (x, y) at each end -- lets two phases that share the same
  // attr_tag (confirmed real for VTM: several distinct coordinates all
  // tag as ttp_storable_io_point) be told apart. null only for a phase
  // built before this field existed (a stale cached trace).
  from_coordinate: [number, number] | null
  to_coordinate: [number, number] | null
}

export type LiftCorrectionMethod = 'telemetry' | 'estimated_buffer' | null
export type LiftDirection = 'up' | 'down' | null

export interface LiftEventDto {
  bot_id: string
  order_sent_at: string | null
  logged_complete_at: string
  target_height_mm: number | null
  corrected_complete_at: string | null
  correction_method: LiftCorrectionMethod
  buffer_ms: number | null
  understated_by_seconds: number | null
  confidence: Confidence
  direction: LiftDirection
  context_label: string | null
  coordinate: [number, number] | null
}

export type RotationSignificance = 'major' | 'minor'
export type RotationMethod = 'telemetry' | 'planned_path_estimate'

export interface RotationEventDto {
  bot_id: string
  timestamp: string
  coordinate: [number, number] | null
  duration_ms: number
  confidence: Confidence
  significance: RotationSignificance
  method: RotationMethod
  context_label: string | null
}

export interface ForkAdjustmentEventDto {
  bot_id: string
  timestamp: string
  started_at: string | null
  from_height_mm: number
  to_height_mm: number
  direction: 'up' | 'down'
  confidence: Confidence
  label: string | null
  coordinate: [number, number] | null
}

export interface ChargeTimingDto {
  assigned_at: string | null
  reached_charger_reinit_at: string | null
  reached_charger_at: string | null
  charging_started_at: string | null
  charging_complete_at: string | null
  return_dispatched_at: string | null
  return_reached_charger_reinit_at: string | null
  parked_at: string | null
  assigned_to_reinit_seconds: number | null
  reinit_to_charger_seconds: number | null
  docked_to_charging_started_seconds: number | null
  outbound_travel_seconds: number | null
  charging_duration_seconds: number | null
  charging_stop_to_reinit_seconds: number | null
  reinit_to_parked_seconds: number | null
  return_travel_seconds: number | null
  total_seconds: number | null
  battery_pct_at_charger_arrival: number | null
  battery_pct_at_charging_complete: number | null
  graceful_stop_at: string | null
  graceful_stop_reason: string | null
  charging_stopped_via_api: boolean
}

export interface TaskTraceDto {
  request_id: string | null
  task_id: string | null
  task_type: string | null
  butler_id: string | null
  status: TaskStatus
  created_at: string | null
  dispatched_at: string | null
  completed_at: string | null
  queued_duration_seconds: number | null
  total_duration_seconds: number | null
  cycle_duration_seconds: number | null
  tote_ids: string[]
  has_warnings_or_errors: boolean
  warning_lines: string[]
  phases: PhaseDto[]
  events: TaskEventDto[]
  lift_events: LiftEventDto[]
  rotation_events: RotationEventDto[]
  fork_adjustment_events: ForkAdjustmentEventDto[]
  charge_timing: ChargeTimingDto | null
}

export interface TaskSummaryDto {
  task_id: string
  task_type: string
  bot_id: string
  created_at: string
  relay_position: string | null
  last_seen_at: string | null
  is_bot_current_task: boolean
}

export interface TaskScanResultDto {
  window_start: string
  tasks: TaskSummaryDto[]
}

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new ApiError(detail.detail ?? resp.statusText, resp.status)
  }
  return resp.json()
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`)
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new ApiError(detail.detail ?? resp.statusText, resp.status)
  }
  return resp.json()
}

export function fetchTaskTrace(params: {
  butlerIp: string
  sshUser?: string
  taskId?: string
  requestId?: string
}): Promise<TaskTraceDto> {
  return postJson('/api/task', {
    butler_ip: params.butlerIp,
    ssh_user: params.sshUser ?? 'gor',
    task_id: params.taskId ?? null,
    request_id: params.requestId ?? null,
  })
}

export interface LiftHeightAggregateDto {
  avg_seconds: number
  sample_count: number
}

export interface AggregateStatsDto {
  window_start: string
  task_count: number
  tasks_with_lift_data: number
  tasks_with_rotation_data: number
  lift_by_target_height_mm: Record<string, LiftHeightAggregateDto>
  rotation: LiftHeightAggregateDto | null
  distinct_bots_processed: string[]
  distinct_bots_skipped: string[]
}

export function fetchAggregateStats(params: {
  butlerIp: string
  sshUser?: string
  lookbackHours?: number
}): Promise<AggregateStatsDto> {
  return postJson('/api/aggregate-stats', {
    butler_ip: params.butlerIp,
    ssh_user: params.sshUser ?? 'gor',
    lookback_hours: params.lookbackHours ?? 24,
  })
}

export function checkConnectivity(butlerIp: string, sshUser = 'gor'): Promise<{ ok: boolean }> {
  return postJson(`/api/connectivity-check?butler_ip=${encodeURIComponent(butlerIp)}&ssh_user=${encodeURIComponent(sshUser)}`, {})
}

export function fetchTaskScan(params: {
  butlerIp: string
  sshUser?: string
  lookbackHours?: number
}): Promise<TaskScanResultDto> {
  return postJson('/api/scan', {
    butler_ip: params.butlerIp,
    ssh_user: params.sshUser ?? 'gor',
    lookback_hours: params.lookbackHours ?? 24,
  })
}

export interface BenchmarkSubEventResultDto {
  kind: 'lift' | 'rotation' | 'fork'
  label: string
  duration_seconds: number
  threshold_seconds: number
  passed: boolean
  sequence_violation: boolean
}

export interface SavedBenchmarkResultDto {
  id: number
  recorded_at: string
  task_type: string | null
  butler_ip: string | null
  thresholds: Record<string, number>
  pass_count: number
  fail_count: number
  results: BenchmarkSubEventResultDto[]
}

export function saveBenchmarkResult(params: {
  taskId: string
  taskType: string | null
  butlerIp: string
  thresholds: Record<string, number>
  results: BenchmarkSubEventResultDto[]
}): Promise<{ id: number; recorded_at: string; pass_count: number; fail_count: number }> {
  return postJson('/api/benchmark-result', {
    task_id: params.taskId,
    task_type: params.taskType,
    butler_ip: params.butlerIp,
    thresholds: params.thresholds,
    results: params.results,
  })
}

export function fetchBenchmarkResults(taskId: string): Promise<{ task_id: string; results: SavedBenchmarkResultDto[] }> {
  return getJson(`/api/benchmark-result/${encodeURIComponent(taskId)}`)
}

export interface FullLogsDto {
  task_id: string
  butler_id: string | null
  window_start: string | null
  window_end: string | null
  line_count: number
  lines: string[]
}

// Every raw log line the task's bot produced during its own window -- NOT
// filtered to task_id mentions or any known lift/rotation/fork marker (see
// backend's grep_bot_all_lines) -- the "give me everything, not just the
// rm-scoped lines" export option.
export function fetchTaskFullLogs(params: {
  butlerIp: string
  sshUser?: string
  taskId?: string
  requestId?: string
}): Promise<FullLogsDto> {
  return postJson('/api/task/full-logs', {
    butler_ip: params.butlerIp,
    ssh_user: params.sshUser ?? 'gor',
    task_id: params.taskId ?? null,
    request_id: params.requestId ?? null,
  })
}
