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
  phases: PhaseDto[]
  events: TaskEventDto[]
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

export function checkConnectivity(butlerIp: string, sshUser = 'gor'): Promise<{ ok: boolean }> {
  return postJson(`/api/connectivity-check?butler_ip=${encodeURIComponent(butlerIp)}&ssh_user=${encodeURIComponent(sshUser)}`, {})
}
