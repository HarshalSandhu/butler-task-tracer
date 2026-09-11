import { useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTaskTrace } from '../hooks/useTaskTrace'
import { TaskSwimlane } from '../components/TaskSwimlane'
import { LoadingIndicator } from '../components/LoadingIndicator'
import { ChargeTimingPanel } from '../components/ChargeTimingPanel'
import { BaselineSettings } from '../components/BaselineSettings'
import { buildTraceUrl } from '../lib/routes'
import {
  baselinesForTaskType,
  loadMovementBaselines,
  loadTaskTypeBaselines,
  saveMovementBaselines,
  saveTaskTypeBaselines,
  type BenchmarkTaskType,
} from '../lib/baselines'

const LAST_SSH_USER_KEY = 'butler-tracer:last-ssh-user'

/** PLAN.md "Single-task deep-dive": stat strip -> swimlane -> raw log table. */
export function TaskDeepDivePage() {
  const { butlerIp = '', taskId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [showRawLines, setShowRawLines] = useState(false)
  const [taskTypeBaselines, setTaskTypeBaselines] = useState(() => loadTaskTypeBaselines())
  const [movementBaselines, setMovementBaselines] = useState(() => loadMovementBaselines())

  const sshUser = searchParams.get('ssh_user') || undefined

  const { data: trace, isLoading, error } = useTaskTrace({ butlerIp, taskId, sshUser })

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-3">
      <SearchBar
        defaultButlerIp={butlerIp}
        defaultTaskId={taskId}
        defaultSshUser={sshUser}
        onSubmit={(ip, id, user) => navigate(buildTraceUrl(ip, id, user))}
      />

      <LoadingIndicator
        active={isLoading}
        label={`Running remote log grep against ${sshUser ?? 'gor'}@${butlerIp} -`}
      />
      {error && <p className="text-red-400 text-sm">{(error as Error).message}</p>}

      {trace && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2 text-sm">
            <Stat label="Task ID" value={trace.task_id ?? '-'} mono />
            <Stat label="Type" value={trace.task_type ?? '-'} />
            <Stat
              label="Status"
              value={trace.status}
              className={
                trace.status === 'completed'
                  ? 'text-green-400'
                  : trace.status === 'failed'
                    ? 'text-red-400'
                    : 'text-yellow-400'
              }
            />
            <Stat
              label="Cycle time (assigned -> completed)"
              value={trace.cycle_duration_seconds ? `${trace.cycle_duration_seconds.toFixed(1)}s` : '-'}
            />
            <Stat label="Butler ID" value={trace.butler_id ?? '-'} />
            <Stat
              label="Tote(s)"
              value={trace.tote_ids.length > 0 ? trace.tote_ids.join(', ') : '-'}
              mono
            />
            <Stat
              label="Queued"
              value={trace.queued_duration_seconds ? `${trace.queued_duration_seconds.toFixed(1)}s` : '-'}
            />
            <Stat
              label="Errors/warnings"
              value={trace.has_warnings_or_errors ? `${trace.warning_lines.length} found` : 'none'}
              className={trace.has_warnings_or_errors ? 'text-red-400' : 'text-green-400'}
            />
            <Stat label="Created" value={trace.created_at ?? '-'} className="text-xs" mono />
            <Stat label="Dispatched (assigned)" value={trace.dispatched_at ?? '-'} className="text-xs" mono />
            <Stat label="Completed" value={trace.completed_at ?? '-'} className="text-xs" mono />
            <Stat
              label="Total duration (creation-based)"
              value={trace.total_duration_seconds ? `${trace.total_duration_seconds.toFixed(1)}s` : '-'}
            />
          </div>

          {trace.charge_timing && (
            <ChargeTimingPanel timing={trace.charge_timing} rotationEvents={trace.rotation_events} />
          )}

          {trace.has_warnings_or_errors && (
            <div className="border border-red-800 bg-red-950/40 rounded p-2">
              <p className="text-xs text-red-300 mb-1">
                {trace.warning_lines.length} warning/error-level line
                {trace.warning_lines.length === 1 ? '' : 's'} observed during this task:
              </p>
              <pre className="text-[10px] text-red-200 overflow-x-auto max-h-40 overflow-y-auto">
                {trace.warning_lines.join('\n')}
              </pre>
            </div>
          )}

          <BaselineSettings
            baselines={taskTypeBaselines}
            activeTaskType={
              trace.task_type === 'relay_group_task' || trace.task_type === 'relay_pps_task'
                ? (trace.task_type as BenchmarkTaskType)
                : undefined
            }
            onChange={(next) => {
              saveTaskTypeBaselines(next)
              setTaskTypeBaselines(next)
            }}
            movementBaselines={movementBaselines}
            onMovementBaselinesChange={(next) => {
              saveMovementBaselines(next)
              setMovementBaselines(next)
            }}
          />

          <TaskSwimlane
            phases={trace.phases}
            events={trace.events}
            liftEvents={trace.lift_events}
            rotationEvents={trace.rotation_events}
            forkAdjustmentEvents={trace.fork_adjustment_events}
            eventBaselines={baselinesForTaskType(taskTypeBaselines, trace.task_type)}
            movementBaselines={movementBaselines}
            taskId={trace.task_id}
            taskType={trace.task_type}
            butlerIp={butlerIp}
          />

          <div>
            <button
              className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors"
              onClick={() => setShowRawLines((s) => !s)}
            >
              {showRawLines ? 'Hide' : 'Show'} raw log lines ({trace.events.length})
            </button>
            {showRawLines && (
              <pre className="mt-2 text-[10px] bg-gray-800 text-gray-200 p-2 rounded-md border border-gray-700 overflow-x-auto max-h-96 overflow-y-auto">
                {trace.events.map((e) => e.raw_line).join('\n')}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  mono,
  className,
}: {
  label: string
  value: string
  mono?: boolean
  className?: string
}) {
  return (
    <div className="border border-gray-700 bg-gray-800/60 rounded-md px-2.5 py-1.5 hover:border-gray-600 transition-colors">
      <div className="text-gray-400 text-[10px]">{label}</div>
      <div
        title={value}
        className={`${mono ? 'font-mono text-xs' : 'text-sm'} break-words ${className ?? ''}`}
      >
        {value}
      </div>
    </div>
  )
}

export function SearchBar({
  defaultButlerIp,
  defaultTaskId,
  defaultSshUser,
  onSubmit,
}: {
  defaultButlerIp: string
  defaultTaskId: string
  defaultSshUser?: string
  onSubmit: (butlerIp: string, taskId: string, sshUser: string) => void
}) {
  const [butlerIp, setButlerIp] = useState(defaultButlerIp)
  const [taskId, setTaskId] = useState(defaultTaskId)
  // Remembers the last SSH user you typed across searches (per-browser,
  // not a global default) - most people only ever hit one or two boxes
  // with one account, so this saves re-typing it every time.
  const [sshUser, setSshUser] = useState(
    defaultSshUser || localStorage.getItem(LAST_SSH_USER_KEY) || '',
  )

  return (
    <form
      className="flex gap-2 items-end flex-wrap"
      onSubmit={(e) => {
        e.preventDefault()
        if (butlerIp && taskId) {
          if (sshUser) localStorage.setItem(LAST_SSH_USER_KEY, sshUser)
          onSubmit(butlerIp, taskId, sshUser)
        }
      }}
    >
      <label className="flex flex-col text-xs text-gray-400 gap-1">
        butler_ip
        <input
          className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2.5 py-1.5 text-sm w-40 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
          value={butlerIp}
          onChange={(e) => setButlerIp(e.target.value)}
          placeholder="172.29.40.48"
        />
      </label>
      <label className="flex flex-col text-xs text-gray-400 gap-1">
        ssh_user
        <input
          className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2.5 py-1.5 text-sm w-40 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
          value={sshUser}
          onChange={(e) => setSshUser(e.target.value)}
          placeholder="gor"
        />
      </label>
      <label className="flex flex-col text-xs text-gray-400 gap-1">
        task_id
        <input
          className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2.5 py-1.5 text-sm w-96 font-mono outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
          placeholder="5fbc8f16-3593-48d2-a7ac-c7cb3826949b"
        />
      </label>
      <button
        type="submit"
        className="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white text-sm font-medium rounded-md px-4 py-1.5 transition-colors"
      >
        Run Analysis
      </button>
      <a
        href={butlerIp && taskId ? buildTraceUrl(butlerIp, taskId, sshUser) : undefined}
        target="_blank"
        rel="noopener noreferrer"
        aria-disabled={!(butlerIp && taskId)}
        onClick={(e) => {
          if (!(butlerIp && taskId)) {
            e.preventDefault()
            return
          }
          if (sshUser) localStorage.setItem(LAST_SSH_USER_KEY, sshUser)
        }}
        title="Open in a new tab, keeping this page as-is"
        className={`text-sm font-medium rounded-md px-4 py-1.5 border transition-colors ${
          butlerIp && taskId
            ? 'border-gray-600 text-gray-200 hover:bg-gray-800'
            : 'border-gray-800 text-gray-600 cursor-not-allowed'
        }`}
      >
        Open in new tab ↗
      </a>
    </form>
  )
}
