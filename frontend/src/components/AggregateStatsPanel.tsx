import type { AggregateStatsDto } from '../lib/api'

/** Averages across every relay_pps_task in the lookback window -- see
 * api/routes.py's /api/aggregate-stats and its module docstring for why
 * lift time is grouped by target fork height rather than blended together. */
export function AggregateStatsPanel({ stats }: { stats: AggregateStatsDto }) {
  const heightEntries = Object.entries(stats.lift_by_target_height_mm).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  )

  if (stats.task_count === 0) {
    return null
  }

  return (
    <div className="border border-gray-700 bg-gray-800/60 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-gray-200">
          relay_pps_task averages - last 24h ({stats.task_count} tasks)
        </h2>
        {stats.distinct_bots_skipped.length > 0 && (
          <span
            className="text-xs text-yellow-400"
            title={`Bots not sampled (over the ${stats.distinct_bots_processed.length}-bot cap): ${stats.distinct_bots_skipped.join(', ')}`}
          >
            {stats.distinct_bots_skipped.length} bot{stats.distinct_bots_skipped.length === 1 ? '' : 's'} not sampled
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-gray-400 mb-1.5">
            Avg. simultaneous-lift time by target fork height
            <span className="text-gray-500"> ({stats.tasks_with_lift_data} tasks with lift data)</span>
          </p>
          {heightEntries.length === 0 ? (
            <p className="text-sm text-gray-500">No lift data in this window.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-gray-500">
                <tr>
                  <th className="pr-3 py-1">Target height</th>
                  <th className="pr-3 py-1">Avg. time</th>
                  <th className="py-1">Samples</th>
                </tr>
              </thead>
              <tbody>
                {heightEntries.map(([heightMm, agg]) => (
                  <tr key={heightMm} className="border-t border-gray-700/60 text-gray-200">
                    <td className="pr-3 py-1 font-mono">{heightMm}mm</td>
                    <td className="pr-3 py-1 font-mono">{agg.avg_seconds.toFixed(2)}s</td>
                    <td className="py-1 text-gray-400">{agg.sample_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <p className="text-xs text-gray-400 mb-1.5">Avg. rotation time overall</p>
          {stats.rotation ? (
            <p className="text-2xl font-semibold text-gray-100">
              {stats.rotation.avg_seconds.toFixed(2)}
              <span className="text-sm text-gray-400 ml-1">s</span>
              <span className="text-xs text-gray-500 ml-2 font-normal">
                ({stats.rotation.sample_count} rotations, {stats.tasks_with_rotation_data} tasks)
              </span>
            </p>
          ) : (
            <p className="text-sm text-gray-500">No rotation data in this window.</p>
          )}
        </div>
      </div>
    </div>
  )
}
