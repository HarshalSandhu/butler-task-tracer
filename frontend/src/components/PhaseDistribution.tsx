import { useMemo } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { type PhaseDuration, computeBaselines, phaseKey } from '../lib/anomaly'

/**
 * Per-phase distribution for the batch/aggregate view (PLAN.md "Batch/
 * aggregate view") - one row per phase key, showing mean/p50/p95 across
 * every task in the queried window. This is the direct generalization of
 * the ad-hoc InfluxDB query built earlier in this tool's design session
 * (e.g. "avg 18-22s, n=67/101" for a relay hop, split by scenario) - here
 * sourced from real parsed traces instead of a pre-existing Influx field.
 *
 * `scenarioLabel` (optional) lets the caller split the same phase key by
 * scenario (e.g. "tote on fork" vs "going to load") via the legend the
 * same way the manual Influx query did - passed through as a grouping key
 * on each duration sample.
 */

export interface ScenarioPhaseDuration extends PhaseDuration {
  scenarioLabel?: string
}

export function PhaseDistribution({ durations }: { durations: ScenarioPhaseDuration[] }) {
  const rows = useMemo(() => {
    const baselines = computeBaselines(durations)
    return Array.from(baselines.values())
      .sort((a, b) => b.sampleCount - a.sampleCount)
      .map((b) => ({
        phase: b.phaseKey,
        mean:
          durations
            .filter((d) => phaseKey(d.fromAttr, d.toAttr) === b.phaseKey)
            .reduce((sum, d) => sum + d.durationSeconds, 0) / b.sampleCount,
        p50: b.p50,
        p95: b.p95,
        n: b.sampleCount,
      }))
  }, [durations])

  if (rows.length === 0) {
    return <p className="text-gray-500 text-sm">No phase data in this window.</p>
  }

  return (
    <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 50)}>
      <BarChart data={rows} layout="vertical" margin={{ left: 24, right: 24 }}>
        <CartesianGrid strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" unit="s" />
        <YAxis type="category" dataKey="phase" width={220} tick={{ fontSize: 11 }} />
        <Tooltip
          formatter={(value, name) => [`${Number(value).toFixed(2)}s`, String(name)]}
          labelFormatter={(_, payload) => (payload?.[0] ? `n=${payload[0].payload.n}` : '')}
        />
        <Legend />
        {/* Grouped (not stacked) bars, one per row, so mean/p50/p95 are
            directly comparable side-by-side for each phase - a per-row
            ReferenceLine isn't possible in Recharts (it always spans the
            full chart height), so this grouped-bar approach is used
            instead. */}
        <Bar dataKey="mean" fill="#60a5fa" name="mean" radius={2} />
        <Bar dataKey="p95" fill="#dc2626" name="p95" radius={2} fillOpacity={0.6} />
      </BarChart>
    </ResponsiveContainer>
  )
}
