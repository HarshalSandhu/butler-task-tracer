import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTaskScan } from '../hooks/useTaskScan'
import { useAggregateStats } from '../hooks/useAggregateStats'
import { TaskScanTable } from '../components/TaskScanTable'
import { LoadingIndicator } from '../components/LoadingIndicator'
import { AggregateStatsPanel } from '../components/AggregateStatsPanel'
import { SearchBar } from './TaskDeepDivePage'
import type { TaskSummaryDto } from '../lib/api'
import { buildTraceUrl } from '../lib/routes'

const LAST_BUTLER_IP_KEY = 'butler-tracer:last-butler-ip'
const LAST_SSH_USER_KEY = 'butler-tracer:last-ssh-user'
const DEFAULT_LOOKBACK_HOURS = 24

type TaskTab = 'all' | 'relay_group_task' | 'relay_pps_task' | 'chargetask'

const TABS: { key: TaskTab; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'relay_group_task', label: 'Relay Group (VTM)' },
  { key: 'relay_pps_task', label: 'Relay PPS (HTM)' },
  { key: 'chargetask', label: 'Charge Task' },
]

/**
 * Landing page: "whenever I login it should get all the task from the
 * server" -- auto-runs the bounded 24h scan (PLAN.md Mode 3) against the
 * last-used butler_ip/ssh_user (persisted per-browser, same pattern as
 * TaskDeepDivePage's ssh_user memory) as soon as one is known, no extra
 * click needed. Falls back to a one-time connect form when neither has
 * been set yet.
 */
export function TaskListPage() {
  const navigate = useNavigate()
  const [butlerIp, setButlerIp] = useState(() => localStorage.getItem(LAST_BUTLER_IP_KEY) ?? '')
  const [sshUser, setSshUser] = useState(() => localStorage.getItem(LAST_SSH_USER_KEY) ?? '')
  const [connectIp, setConnectIp] = useState('')
  const [connectUser, setConnectUser] = useState('gor')
  const [activeTab, setActiveTab] = useState<TaskTab>('all')

  const { data, error, refetch, isFetching } = useTaskScan({
    butlerIp: butlerIp || null,
    sshUser: sshUser || undefined,
    lookbackHours: DEFAULT_LOOKBACK_HOURS,
  })
  const {
    data: aggregateStats,
    error: aggregateError,
    isFetching: isFetchingAggregate,
  } = useAggregateStats({
    butlerIp: butlerIp || null,
    sshUser: sshUser || undefined,
    lookbackHours: DEFAULT_LOOKBACK_HOURS,
  })

  const tabCounts: Record<TaskTab, number> = {
    all: data?.tasks.length ?? 0,
    relay_group_task: data?.tasks.filter((t) => t.task_type === 'relay_group_task').length ?? 0,
    relay_pps_task: data?.tasks.filter((t) => t.task_type === 'relay_pps_task').length ?? 0,
    chargetask: data?.tasks.filter((t) => t.task_type === 'chargetask').length ?? 0,
  }
  const visibleTasks =
    activeTab === 'all' ? (data?.tasks ?? []) : (data?.tasks.filter((t) => t.task_type === activeTab) ?? [])

  const buildTraceHref = (task: TaskSummaryDto) => buildTraceUrl(butlerIp, task.task_id, sshUser)

  const handleRowClick = (task: TaskSummaryDto) => {
    navigate(buildTraceHref(task))
  }

  const connect = (e: React.FormEvent) => {
    e.preventDefault()
    if (!connectIp) return
    localStorage.setItem(LAST_BUTLER_IP_KEY, connectIp)
    if (connectUser) localStorage.setItem(LAST_SSH_USER_KEY, connectUser)
    setButlerIp(connectIp)
    setSshUser(connectUser)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600/20 text-blue-400 text-lg">
          🤖
        </span>
        <div>
          <h1 className="text-xl font-semibold text-gray-100 tracking-tight">Butler Task Lifecycle Tracer</h1>
          <p className="text-sm text-gray-400">Read-only observability over SSH - see the README for scope.</p>
        </div>
      </div>

      {!butlerIp ? (
        <form
          className="flex gap-3 items-end flex-wrap border border-gray-700 bg-gray-800/60 rounded-lg p-5 shadow-sm"
          onSubmit={connect}
        >
          <label className="flex flex-col text-xs text-gray-400 gap-1">
            butler_ip
            <input
              className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2.5 py-1.5 text-sm w-40 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
              value={connectIp}
              onChange={(e) => setConnectIp(e.target.value)}
              placeholder="172.29.40.48"
            />
          </label>
          <label className="flex flex-col text-xs text-gray-400 gap-1">
            ssh_user
            <input
              className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2.5 py-1.5 text-sm w-40 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
              value={connectUser}
              onChange={(e) => setConnectUser(e.target.value)}
              placeholder="gor"
            />
          </label>
          <button
            type="submit"
            className="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 text-white text-sm font-medium rounded-md px-4 py-1.5 transition-colors"
          >
            Connect
          </button>
        </form>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="text-sm text-gray-300">
              Last {DEFAULT_LOOKBACK_HOURS}h on{' '}
              <span className="font-mono text-gray-200">
                {sshUser || 'gor'}@{butlerIp}
              </span>
              {data && (
                <span className="ml-2 inline-flex items-center rounded-full bg-blue-600/20 text-blue-300 text-xs px-2 py-0.5">
                  {data.tasks.length} tasks
                </span>
              )}
            </div>
            <div className="flex items-center gap-4">
              <button
                className="text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2 disabled:text-gray-500 disabled:no-underline transition-colors"
                onClick={() => refetch()}
                disabled={isFetching}
              >
                Refresh
              </button>
              <button
                className="text-xs text-gray-400 hover:text-gray-300 underline underline-offset-2 transition-colors"
                onClick={() => setButlerIp('')}
              >
                Change target
              </button>
            </div>
          </div>

          <LoadingIndicator
            active={isFetching}
            label={`Scanning last ${DEFAULT_LOOKBACK_HOURS}h of debug.log* on ${butlerIp} (greps every rotated log file that could overlap the window) -`}
          />
          {error && (
            <p className="text-red-400 text-sm bg-red-950/30 border border-red-900 rounded-md px-3 py-2">
              {(error as Error).message}
            </p>
          )}

          {data && (
            <div className="flex gap-1 border-b border-gray-700">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`text-sm px-3 py-2 border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-blue-500 text-blue-300'
                      : 'border-transparent text-gray-400 hover:text-gray-200'
                  }`}
                >
                  {tab.label} <span className="text-xs text-gray-500">({tabCounts[tab.key]})</span>
                </button>
              ))}
            </div>
          )}
          {data && <TaskScanTable tasks={visibleTasks} onRowClick={handleRowClick} getHref={buildTraceHref} />}

          <LoadingIndicator
            active={isFetchingAggregate}
            label="Computing relay_pps_task lift/rotation averages for the last 24h -"
          />
          {aggregateError && (
            <p className="text-red-400 text-sm bg-red-950/30 border border-red-900 rounded-md px-3 py-2">
              {(aggregateError as Error).message}
            </p>
          )}
          {aggregateStats && <AggregateStatsPanel stats={aggregateStats} />}
        </div>
      )}

      <div className="border-t border-gray-700 pt-4">
        <p className="text-xs text-gray-400 mb-2">Or trace a specific task/request directly:</p>
        <SearchBar
          defaultButlerIp={butlerIp}
          defaultTaskId=""
          defaultSshUser={sshUser}
          onSubmit={(ip, id, user) => navigate(buildTraceUrl(ip, id, user))}
        />
      </div>
    </div>
  )
}
