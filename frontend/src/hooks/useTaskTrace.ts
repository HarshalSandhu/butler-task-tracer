import { useQuery } from '@tanstack/react-query'
import { fetchTaskTrace, type TaskTraceDto } from '../lib/api'

/**
 * Wraps the single-task lookup (PLAN.md Mode 1) in TanStack Query, which
 * gives us the loading/error states an SSH-grep-backed request needs for
 * free (this can take a few seconds against a real remote log file).
 */
export function useTaskTrace(params: {
  butlerIp: string | null
  taskId: string | null
  sshUser?: string
}) {
  return useQuery<TaskTraceDto>({
    queryKey: ['task-trace', params.butlerIp, params.taskId, params.sshUser],
    queryFn: () =>
      fetchTaskTrace({
        butlerIp: params.butlerIp!,
        taskId: params.taskId!,
        sshUser: params.sshUser,
      }),
    enabled: Boolean(params.butlerIp && params.taskId),
    staleTime: 60_000, // logs are append-only; a completed trace never changes
    retry: false, // a 404/502 here is a real answer, not a transient failure
  })
}
