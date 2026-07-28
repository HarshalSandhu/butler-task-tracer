import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { PhaseDto, TaskEventDto } from '../lib/api'
import { type PhaseBaseline, checkAnomaly, phaseKey } from '../lib/anomaly'

/**
 * Gantt/swimlane view of one task's phase-by-phase movement, per
 * PLAN.md "Timeline visualization approach": one row per phase, bar
 * length = duration, color keyed by the grid `attr_tag` (this mapping
 * already exists in the data - relay_storable_io_point, relay_storable,
 * pps_entry_queue, pps, highway, etc.). Non-movement events (fork height
 * changes, tote load, pps_control) render as markers on a thin row below,
 * not as bars, since they're instantaneous actions.
 *
 * Recharts has no native Gantt type - this uses the standard
 * offset-bar technique: an invisible bar from 0 to `start`, stacked with
 * a visible bar from `start` to `start + duration`.
 */

const ATTR_COLORS: Record<string, string> = {
  relay_storable_io_point: '#60a5fa',
  relay_storable: '#34d399',
  pps_entry_queue: '#fbbf24',
  pps: '#f97316',
  highway: '#a78bfa',
  charger: '#f43f5e',
  charger_reinit: '#ec4899',
}
const DEFAULT_COLOR = '#9ca3af'

function attrColor(attr: string | null): string {
  if (!attr) return DEFAULT_COLOR
  return ATTR_COLORS[attr] ?? DEFAULT_COLOR
}

interface Row {
  label: string
  offset: number
  duration: number
  attr: string
  fromAttr: string | null
  startIso: string
  isAnomalous: boolean
  multipleOfP95: number | null
}

export function TaskSwimlane({
  phases,
  events,
  baselines,
}: {
  phases: PhaseDto[]
  events: TaskEventDto[]
  baselines?: Map<string, PhaseBaseline>
}) {
  const taskStart = phases.length > 0 ? new Date(phases[0].timestamp).getTime() : 0

  const rows: Row[] = useMemo(() => {
    return phases.map((p, i) => {
      const endMs = new Date(p.timestamp).getTime()
      const startMs = endMs - p.duration_seconds * 1000
      const offset = (startMs - taskStart) / 1000
      const anomaly = baselines
        ? checkAnomaly(
            { fromAttr: p.from_attr, toAttr: p.to_attr, durationSeconds: p.duration_seconds },
            baselines,
          )
        : { isAnomalous: false, multipleOfP95: null }
      return {
        label: `${i + 1}. ${p.from_attr ?? '?'} -> ${p.to_attr}`,
        offset,
        duration: p.duration_seconds,
        attr: p.to_attr,
        fromAttr: p.from_attr,
        startIso: p.timestamp,
        isAnomalous: anomaly.isAnomalous,
        multipleOfP95: anomaly.multipleOfP95,
      }
    })
  }, [phases, taskStart, baselines])

  const nonMovementEvents = events.filter((e) => !e.attr_tag)

  if (phases.length === 0) {
    return <p className="text-gray-500 text-sm">No movement phases found for this task.</p>
  }

  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={Math.max(200, rows.length * 40)}>
        <BarChart data={rows} layout="vertical" margin={{ left: 24, right: 24 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            unit="s"
            label={{ value: 'Seconds since task start', position: 'insideBottom', offset: -5 }}
          />
          <YAxis type="category" dataKey="label" width={220} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(_value, _name, props) => {
              const row = props.payload as Row
              return [
                `${row.duration.toFixed(2)}s${row.multipleOfP95 ? ` (${row.multipleOfP95.toFixed(1)}x p95)` : ''}`,
                row.label,
              ]
            }}
          />
          {/* invisible spacer bar */}
          <Bar dataKey="offset" stackId="a" fill="transparent" isAnimationActive={false} />
          {/* the actual visible phase-duration bar */}
          <Bar dataKey="duration" stackId="a" isAnimationActive={false} radius={2}>
            {rows.map((row, i) => (
              <Cell
                key={phaseKey(row.fromAttr, row.attr) + i}
                fill={attrColor(row.attr)}
                stroke={row.isAnomalous ? '#dc2626' : undefined}
                strokeWidth={row.isAnomalous ? 3 : 0}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {nonMovementEvents.length > 0 && (
        <div className="border-t pt-2">
          <p className="text-xs text-gray-500 mb-1">Non-movement actions</p>
          <div className="flex flex-wrap gap-2">
            {nonMovementEvents.map((e, i) => (
              <span
                key={i}
                title={e.raw_line}
                className="inline-flex items-center gap-1 text-xs bg-gray-100 rounded px-2 py-1"
              >
                <span className="inline-block w-2 h-2 rotate-45 bg-gray-500" />
                {e.phase_label ?? e.function}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
