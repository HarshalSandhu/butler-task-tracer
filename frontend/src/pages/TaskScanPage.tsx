import { useSearchParams, useParams, useNavigate } from 'react-router-dom'
import { useTaskScan } from '../hooks/useTaskScan'
import { TaskScanTable } from '../components/TaskScanTable'
import { LoadingIndicator } from '../components/LoadingIndicator'
import type { TaskSummaryDto } from '../lib/api'

/** URL-addressable version of the same scan TaskListPage runs on load --
 * lets a specific butler_ip's scan be bookmarked/shared directly. */
export function TaskScanPage() {
  const { butlerIp = '' } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const sshUser = searchParams.get('ssh_user') || undefined

  const { data, isLoading, error } = useTaskScan({ butlerIp, sshUser })

  const handleRowClick = (task: TaskSummaryDto) => {
    const qs = sshUser ? `?ssh_user=${encodeURIComponent(sshUser)}` : ''
    navigate(`/trace/${butlerIp}/task/${task.task_id}${qs}`)
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      <h1 className="text-lg font-semibold text-gray-100">
        Last 24h on <span className="font-mono">{butlerIp}</span>
      </h1>
      <LoadingIndicator active={isLoading} label="Scanning -" />
      {error && <p className="text-red-400 text-sm">{(error as Error).message}</p>}
      {data && <TaskScanTable tasks={data.tasks} onRowClick={handleRowClick} />}
    </div>
  )
}
