import { useQuery } from '@tanstack/react-query'
import { fetchTaskScan, type TaskScanResultDto } from '../lib/api'

/** Mode 3 (bounded "Full Scan"), see api/routes.py's /api/scan. */
export function useTaskScan(params: {
  butlerIp: string | null
  sshUser?: string
  lookbackHours?: number
}) {
  return useQuery<TaskScanResultDto>({
    queryKey: ['task-scan', params.butlerIp, params.sshUser, params.lookbackHours],
    queryFn: () =>
      fetchTaskScan({
        butlerIp: params.butlerIp!,
        sshUser: params.sshUser,
        lookbackHours: params.lookbackHours,
      }),
    enabled: Boolean(params.butlerIp),
    staleTime: 30_000,
    retry: false,
  })
}
