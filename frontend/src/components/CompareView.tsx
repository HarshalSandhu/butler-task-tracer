import type { TaskTraceDto } from '../lib/api'
import { TaskSwimlane } from './TaskSwimlane'

/**
 * Side-by-side comparison of two task traces (PLAN.md "Crazy tool" v1
 * feature #2) - stacked swimlanes on a shared, phase-start-normalized
 * (not wall-clock) axis, since TaskSwimlane already renders relative to
 * its own task's start time. Rendering both instances stacked achieves
 * the normalization for free; a diff strip below highlights per-phase
 * deltas for the phases that exist in both traces.
 */
export function CompareView({ traceA, traceB }: { traceA: TaskTraceDto; traceB: TaskTraceDto }) {
  const diffRows = diffPhases(traceA, traceB)

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-medium mb-1">
          Task A: {traceA.task_id} ({traceA.total_duration_seconds?.toFixed(1)}s total)
        </h3>
        <TaskSwimlane phases={traceA.phases} events={traceA.events} />
      </div>
      <div>
        <h3 className="text-sm font-medium mb-1">
          Task B: {traceB.task_id} ({traceB.total_duration_seconds?.toFixed(1)}s total)
        </h3>
        <TaskSwimlane phases={traceB.phases} events={traceB.events} />
      </div>

      {diffRows.length > 0 && (
        <div className="border-t pt-3">
          <h4 className="text-sm font-medium mb-2">Per-phase difference (B - A)</h4>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="pb-1">Phase</th>
                <th className="pb-1">A</th>
                <th className="pb-1">B</th>
                <th className="pb-1">Delta</th>
              </tr>
            </thead>
            <tbody>
              {diffRows.map((row) => (
                <tr key={row.phase} className={Math.abs(row.deltaSeconds) > 5 ? 'text-red-600' : ''}>
                  <td className="py-0.5">{row.phase}</td>
                  <td>{row.aSeconds.toFixed(2)}s</td>
                  <td>{row.bSeconds.toFixed(2)}s</td>
                  <td>
                    {row.deltaSeconds >= 0 ? '+' : ''}
                    {row.deltaSeconds.toFixed(2)}s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function diffPhases(a: TaskTraceDto, b: TaskTraceDto) {
  const keyOf = (fromAttr: string | null, toAttr: string) => `${fromAttr ?? '?'}->${toAttr}`
  const aByKey = new Map(a.phases.map((p) => [keyOf(p.from_attr, p.to_attr), p.duration_seconds]))
  const bByKey = new Map(b.phases.map((p) => [keyOf(p.from_attr, p.to_attr), p.duration_seconds]))

  const rows: { phase: string; aSeconds: number; bSeconds: number; deltaSeconds: number }[] = []
  for (const [key, aSeconds] of aByKey) {
    const bSeconds = bByKey.get(key)
    if (bSeconds !== undefined) {
      rows.push({ phase: key, aSeconds, bSeconds, deltaSeconds: bSeconds - aSeconds })
    }
  }
  return rows
}
