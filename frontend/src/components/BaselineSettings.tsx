import { useState } from 'react'
import type { BenchmarkTaskType, EventBaselines, MovementBaseline, TaskTypeBaselines } from '../lib/baselines'

const TASK_TYPE_LABELS: Record<BenchmarkTaskType, string> = {
  relay_group_task: 'Relay Group Task (VTM)',
  relay_pps_task: 'Relay PPS Task (HTM)',
}

/** Collapsible editor for the manual pass/fail thresholds every lift/
 * rotation/fork-adjustment row in TaskSwimlane gets benchmarked against --
 * one set of thresholds per task type (VTM and HTM are physically
 * different mechanisms, see lib/baselines.ts). Persists per-browser --
 * there's no server-side concept of "the right number", the user sets it. */
export function BaselineSettings({
  baselines,
  activeTaskType,
  onChange,
  movementBaselines,
  onMovementBaselinesChange,
}: {
  baselines: TaskTypeBaselines
  activeTaskType?: BenchmarkTaskType
  onChange: (next: TaskTypeBaselines) => void
  // Optional -- omit to hide the movement-threshold editor entirely (e.g.
  // a caller that doesn't yet have anywhere to persist these).
  movementBaselines?: MovementBaseline[]
  onMovementBaselinesChange?: (next: MovementBaseline[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(baselines)
  const [movementDraft, setMovementDraft] = useState(movementBaselines ?? [])

  const dirty = JSON.stringify(draft) !== JSON.stringify(baselines)
  const movementDirty = JSON.stringify(movementDraft) !== JSON.stringify(movementBaselines ?? [])

  const summary = (Object.keys(TASK_TYPE_LABELS) as BenchmarkTaskType[])
    .map((t) => {
      const b = baselines[t]
      return `${t === 'relay_group_task' ? 'VTM' : 'HTM'}: lift ≤${b.liftMaxSeconds}s, rotation ≤${b.rotationMaxSeconds}s, fork ≤${b.forkMaxSeconds}s`
    })
    .join('  |  ')

  return (
    <div className="border border-gray-700 bg-gray-800/60 rounded-md">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full text-left px-3 py-2 text-sm text-gray-200 hover:text-gray-100 transition-colors"
      >
        <span>
          Benchmark thresholds <span className="text-gray-500 text-xs">({summary})</span>
        </span>
        <span className="text-gray-500 text-xs">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 px-3 pb-3">
          {(Object.keys(TASK_TYPE_LABELS) as BenchmarkTaskType[]).map((taskType) => (
            <div key={taskType} className="flex flex-wrap items-end gap-3 border-t border-gray-700 pt-3 first:border-t-0 first:pt-0">
              <span className="text-xs font-medium text-gray-300 w-44">
                {TASK_TYPE_LABELS[taskType]}
                {activeTaskType === taskType && (
                  <span className="ml-1.5 inline-flex items-center rounded-full bg-blue-600/20 text-blue-300 text-[10px] px-1.5 py-0.5">
                    active
                  </span>
                )}
              </span>
              <TaskTypeFields
                values={draft[taskType]}
                onChange={(next) => setDraft((d) => ({ ...d, [taskType]: next }))}
              />
            </div>
          ))}
          <div>
            <button
              type="button"
              disabled={!dirty}
              onClick={() => onChange(draft)}
              className="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded-md px-3 py-1.5 transition-colors"
            >
              Save
            </button>
          </div>

          {onMovementBaselinesChange && (
            <div className="border-t border-gray-700 pt-3 flex flex-col gap-2">
              <span className="text-xs font-medium text-gray-300">
                Movement (phase) thresholds -- absolute ceiling per attr pair, applies with no history needed
              </span>
              {movementDraft.map((m, i) => (
                <div key={i} className="flex flex-wrap items-end gap-2">
                  <Field
                    label="From attr"
                    text
                    value={m.fromAttr}
                    onChange={(v) => setMovementDraft((d) => d.map((x, j) => (j === i ? { ...x, fromAttr: v } : x)))}
                  />
                  <Field
                    label="To attr"
                    text
                    value={m.toAttr}
                    onChange={(v) => setMovementDraft((d) => d.map((x, j) => (j === i ? { ...x, toAttr: v } : x)))}
                  />
                  <Field
                    label="Max (s)"
                    value={m.maxSeconds}
                    onChange={(v) => setMovementDraft((d) => d.map((x, j) => (j === i ? { ...x, maxSeconds: v } : x)))}
                  />
                  <button
                    type="button"
                    onClick={() => setMovementDraft((d) => d.filter((_, j) => j !== i))}
                    className="text-red-400 hover:text-red-300 text-xs border border-gray-700 rounded px-2 py-1.5 transition-colors"
                  >
                    Remove
                  </button>
                </div>
              ))}
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setMovementDraft((d) => [...d, { fromAttr: '', toAttr: '', maxSeconds: 3 }])}
                  className="text-gray-300 hover:text-gray-100 text-xs border border-gray-700 rounded px-2 py-1.5 transition-colors"
                >
                  + Add movement threshold
                </button>
                <button
                  type="button"
                  disabled={!movementDirty}
                  onClick={() => onMovementBaselinesChange(movementDraft)}
                  className="bg-blue-600 hover:bg-blue-500 active:bg-blue-700 disabled:bg-gray-700 disabled:text-gray-500 text-white text-xs font-medium rounded-md px-3 py-1.5 transition-colors"
                >
                  Save
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TaskTypeFields({
  values,
  onChange,
}: {
  values: EventBaselines
  onChange: (next: EventBaselines) => void
}) {
  return (
    <>
      <Field
        label="Lift max (s)"
        value={values.liftMaxSeconds}
        onChange={(v) => onChange({ ...values, liftMaxSeconds: v })}
      />
      <Field
        label="Rotation max (s)"
        value={values.rotationMaxSeconds}
        onChange={(v) => onChange({ ...values, rotationMaxSeconds: v })}
      />
      <Field
        label="Fork adjustment max (s)"
        value={values.forkMaxSeconds}
        onChange={(v) => onChange({ ...values, forkMaxSeconds: v })}
      />
    </>
  )
}

function Field(
  props:
    | { label: string; value: number; onChange: (value: number) => void; text?: false }
    | { label: string; value: string; onChange: (value: string) => void; text: true },
) {
  const { label, value } = props
  return (
    <label className="flex flex-col text-xs text-gray-400 gap-1">
      {label}
      <input
        type={props.text ? 'text' : 'number'}
        step={props.text ? undefined : '0.5'}
        min={props.text ? undefined : '0'}
        value={value}
        onChange={(e) => (props.text ? props.onChange(e.target.value) : props.onChange(Number(e.target.value)))}
        className="border border-gray-700 bg-gray-800 text-gray-100 rounded-md px-2 py-1 text-sm w-28 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-colors"
      />
    </label>
  )
}
