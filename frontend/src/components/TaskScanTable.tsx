import type { TaskSummaryDto } from '../lib/api'

const TASK_TYPE_LABEL: Record<string, string> = {
  relay_group_task: 'Relay Group (VTM)',
  relay_pps_task: 'Relay PPS (HTM)',
  chargetask: 'Charge Task',
}

function formatExactTimestamp(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString(undefined, { hour12: false })}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

/** Presentable task_id/bot/relay-position list -- PLAN.md "Full Scan" result
 * rendering. Purely presentational: callers own fetching and navigation. */
export function TaskScanTable({
  tasks,
  onRowClick,
  getHref,
}: {
  tasks: TaskSummaryDto[]
  onRowClick: (task: TaskSummaryDto) => void
  getHref: (task: TaskSummaryDto) => string
}) {
  if (tasks.length === 0) {
    return (
      <div className="text-center py-10 border border-dashed border-gray-700 rounded-lg">
        <p className="text-gray-400 text-sm">No tasks found in this window.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto border border-gray-700 rounded-lg">
      <table className="w-full text-sm">
        <thead className="bg-gray-800 text-left text-xs text-gray-400 uppercase sticky top-0">
          <tr>
            <th className="px-3 py-2.5">Task ID</th>
            <th className="px-3 py-2.5">Type</th>
            <th className="px-3 py-2.5">Bot</th>
            <th className="px-3 py-2.5">Relay position</th>
            <th className="px-3 py-2.5">Started (exact)</th>
            <th className="px-3 py-2.5">Status</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr
              key={t.task_id}
              className="border-t border-gray-700 hover:bg-gray-800/80 cursor-pointer text-gray-200 transition-colors"
              onClick={() => onRowClick(t)}
            >
              <td className="px-3 py-2.5 font-mono text-xs">
                <span className="inline-flex items-center gap-1.5">
                  {t.task_id}
                  <a
                    href={getHref(t)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open in new tab"
                    onClick={(e) => e.stopPropagation()}
                    className="text-gray-500 hover:text-blue-400 transition-colors"
                  >
                    ↗
                  </a>
                </span>
              </td>
              <td className="px-3 py-2.5">{TASK_TYPE_LABEL[t.task_type] ?? t.task_type}</td>
              <td className="px-3 py-2.5">{t.bot_id}</td>
              <td className="px-3 py-2.5">
                {t.relay_position ?? <span className="text-gray-500">-</span>}
              </td>
              <td className="px-3 py-2.5 text-xs text-gray-400 font-mono">
                {formatExactTimestamp(t.created_at)}
              </td>
              <td className="px-3 py-2.5">
                <span
                  className={`text-xs rounded-full px-2 py-0.5 ${
                    t.is_bot_current_task
                      ? 'bg-yellow-900 text-yellow-300'
                      : 'bg-gray-700 text-gray-300'
                  }`}
                >
                  {t.is_bot_current_task ? 'active' : 'done'}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
