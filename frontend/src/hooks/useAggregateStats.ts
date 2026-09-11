import { useQuery } from '@tanstack/react-query'
import { fetchAggregateStats, type AggregateStatsDto } from '../lib/api'

/** Average simultaneous-lift time (by target fork height) and average
 * rotation time across every relay_pps_task in the lookback window --
 * see api/routes.py's /api/aggregate-stats. */
export function useAggregateStats(params: {
  butlerIp: string | null
  sshUser?: string
  lookbackHours?: number
}) {
  return useQuery<AggregateStatsDto>({
    queryKey: ['aggregate-stats', params.butlerIp, params.sshUser, params.lookbackHours],
    queryFn: () =>
      fetchAggregateStats({
        butlerIp: params.butlerIp!,
        sshUser: params.sshUser,
        lookbackHours: params.lookbackHours,
      }),
    enabled: Boolean(params.butlerIp),
    staleTime: 60_000,
    retry: false,
  })
}
