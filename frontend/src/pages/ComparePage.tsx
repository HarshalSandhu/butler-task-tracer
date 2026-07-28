import { useParams } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'
import { useTaskTrace } from '../hooks/useTaskTrace'
import { CompareView } from '../components/CompareView'

/** URL: /trace/:butlerIp/compare?a=:taskId&b=:taskId - PLAN.md "Compare view". */
export function ComparePage() {
  const { butlerIp = '' } = useParams()
  const [searchParams] = useSearchParams()
  const taskA = searchParams.get('a') ?? ''
  const taskB = searchParams.get('b') ?? ''

  const { data: traceA, isLoading: loadingA, error: errorA } = useTaskTrace({ butlerIp, taskId: taskA })
  const { data: traceB, isLoading: loadingB, error: errorB } = useTaskTrace({ butlerIp, taskId: taskB })

  if (!taskA || !taskB) {
    return <p className="p-6 text-gray-500">Provide both ?a=task_id and ?b=task_id to compare.</p>
  }
  if (loadingA || loadingB) return <p className="p-6 text-gray-500">Loading both traces...</p>
  if (errorA || errorB) {
    return (
      <p className="p-6 text-red-600 text-sm">
        {errorA ? `Task A: ${(errorA as Error).message}` : ''}
        {errorB ? `Task B: ${(errorB as Error).message}` : ''}
      </p>
    )
  }
  if (!traceA || !traceB) return null

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <CompareView traceA={traceA} traceB={traceB} />
    </div>
  )
}
