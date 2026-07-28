import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTaskTrace } from '../hooks/useTaskTrace'
import { TaskSwimlane } from '../components/TaskSwimlane'

/** PLAN.md "Single-task deep-dive": stat strip -> swimlane -> raw log table. */
export function TaskDeepDivePage() {
  const { butlerIp = '', taskId = '' } = useParams()
  const navigate = useNavigate()
  const [showRawLines, setShowRawLines] = useState(false)

  const { data: trace, isLoading, error } = useTaskTrace({ butlerIp, taskId })

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <SearchBar
        defaultButlerIp={butlerIp}
        defaultTaskId={taskId}
        onSubmit={(ip, id) => navigate(`/trace/${ip}/task/${id}`)}
      />

      {isLoading && <p className="text-gray-500">Running remote log grep against {butlerIp}...</p>}
      {error && <p className="text-red-600 text-sm">{(error as Error).message}</p>}

      {trace && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <Stat label="Task ID" value={trace.task_id ?? '-'} mono />
            <Stat label="Type" value={trace.task_type ?? '-'} />
            <Stat
              label="Status"
              value={trace.status}
              className={
                trace.status === 'completed'
                  ? 'text-green-600'
                  : trace.status === 'failed'
                    ? 'text-red-600'
                    : 'text-yellow-600'
              }
            />
            <Stat
              label="Total duration"
              value={trace.total_duration_seconds ? `${trace.total_duration_seconds.toFixed(1)}s` : '-'}
            />
            <Stat label="Butler ID" value={trace.butler_id ?? '-'} />
            <Stat
              label="Queued"
              value={trace.queued_duration_seconds ? `${trace.queued_duration_seconds.toFixed(1)}s` : '-'}
            />
            <Stat label="Created" value={trace.created_at ?? '-'} className="text-xs" />
            <Stat label="Completed" value={trace.completed_at ?? '-'} className="text-xs" />
          </div>

          <TaskSwimlane phases={trace.phases} events={trace.events} />

          <div>
            <button
              className="text-xs text-blue-600 underline"
              onClick={() => setShowRawLines((s) => !s)}
            >
              {showRawLines ? 'Hide' : 'Show'} raw log lines ({trace.events.length})
            </button>
            {showRawLines && (
              <pre className="mt-2 text-[10px] bg-gray-50 p-2 rounded overflow-x-auto max-h-96 overflow-y-auto">
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
    <div className="border rounded p-2">
      <div className="text-gray-500 text-xs">{label}</div>
      <div className={`${mono ? 'font-mono text-xs' : ''} ${className ?? ''}`}>{value}</div>
    </div>
  )
}

export function SearchBar({
  defaultButlerIp,
  defaultTaskId,
  onSubmit,
}: {
  defaultButlerIp: string
  defaultTaskId: string
  onSubmit: (butlerIp: string, taskId: string) => void
}) {
  const [butlerIp, setButlerIp] = useState(defaultButlerIp)
  const [taskId, setTaskId] = useState(defaultTaskId)

  return (
    <form
      className="flex gap-2 items-end"
      onSubmit={(e) => {
        e.preventDefault()
        if (butlerIp && taskId) onSubmit(butlerIp, taskId)
      }}
    >
      <label className="flex flex-col text-xs text-gray-500">
        butler_ip
        <input
          className="border rounded px-2 py-1 text-sm w-40"
          value={butlerIp}
          onChange={(e) => setButlerIp(e.target.value)}
          placeholder="172.29.40.48"
        />
      </label>
      <label className="flex flex-col text-xs text-gray-500">
        task_id
        <input
          className="border rounded px-2 py-1 text-sm w-96 font-mono"
          value={taskId}
          onChange={(e) => setTaskId(e.target.value)}
          placeholder="5fbc8f16-3593-48d2-a7ac-c7cb3826949b"
        />
      </label>
      <button type="submit" className="bg-blue-600 text-white text-sm rounded px-3 py-1.5">
        Run Analysis
      </button>
    </form>
  )
}
