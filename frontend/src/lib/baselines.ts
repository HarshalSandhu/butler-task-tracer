/**
 * Manually-set benchmark thresholds for lift/rotation/fork-adjustment
 * timing -- per-browser (localStorage), not computed from history. The
 * user sets what "should" take, and every sub-event gets compared
 * against it directly (see TaskSwimlane.tsx's pass/fail badges).
 *
 * Kept separately per task type -- relay_group_task (VTM) and
 * relay_pps_task (HTM) use entirely different fork mechanisms
 * (setForkHeight/tote_load/tote_unload vs simultaneousForkLift/
 * htm_load_tote/htm_unload_tote, see lift_events.py) with different real
 * timing profiles, so one global "lift should take Xs" threshold doesn't
 * fit both bot types.
 */

export interface EventBaselines {
  liftMaxSeconds: number
  rotationMaxSeconds: number
  forkMaxSeconds: number
}

export type BenchmarkTaskType = 'relay_group_task' | 'relay_pps_task'

export type TaskTypeBaselines = Record<BenchmarkTaskType, EventBaselines>

const STORAGE_KEY = 'butler-tracer:event-baselines-by-type'

export const DEFAULT_TASK_TYPE_BASELINES: TaskTypeBaselines = {
  relay_group_task: { liftMaxSeconds: 5, rotationMaxSeconds: 3, forkMaxSeconds: 15 },
  // HTM's in-place rotation benchmark: 2.6s (tightened from the earlier
  // 3s default, which was VTM's number reused for HTM rather than a
  // number specific to HTM's own mechanism).
  relay_pps_task: { liftMaxSeconds: 5, rotationMaxSeconds: 2.6, forkMaxSeconds: 15 },
}

export function loadTaskTypeBaselines(): TaskTypeBaselines {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_TASK_TYPE_BASELINES
    const parsed = JSON.parse(raw)
    return {
      relay_group_task: { ...DEFAULT_TASK_TYPE_BASELINES.relay_group_task, ...parsed.relay_group_task },
      relay_pps_task: { ...DEFAULT_TASK_TYPE_BASELINES.relay_pps_task, ...parsed.relay_pps_task },
    }
  } catch {
    return DEFAULT_TASK_TYPE_BASELINES
  }
}

export function saveTaskTypeBaselines(baselines: TaskTypeBaselines): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(baselines))
}

/** Resolves whichever bucket applies to a trace's own task_type -- falls
 * back to relay_pps_task's numbers for any other/unknown type (e.g.
 * chargetask, or a type not yet classified) rather than a third, separate
 * "default" bucket nobody would think to configure. */
export function baselinesForTaskType(all: TaskTypeBaselines, taskType: string | null | undefined): EventBaselines {
  if (taskType === 'relay_group_task' || taskType === 'relay_pps_task') return all[taskType]
  return all.relay_pps_task
}

/**
 * Manual, per-phase-movement thresholds -- same "user sets what 'should'
 * take" model as EventBaselines above, but for the movement (phase) rows
 * themselves rather than lift/rotation/fork sub-events. Phases ALSO get a
 * separate, automatic anomaly flag from historical p50/p95 (see
 * lib/anomaly.ts) -- that one requires >=5 prior samples and flags
 * relative drift; this one is a manual absolute ceiling the user sets
 * directly, and applies even with zero history. Not split by task type:
 * relay attrs (relay_storable_io_point/relay_storable) are shared naming
 * across HTM/VTM, and only one movement has a manual threshold from the
 * user so far -- add task-type splitting here if that stops being true.
 */
export interface MovementBaseline {
  fromAttr: string
  toAttr: string
  maxSeconds: number
}

const MOVEMENT_STORAGE_KEY = 'butler-tracer:movement-baselines'

export const DEFAULT_MOVEMENT_BASELINES: MovementBaseline[] = [
  { fromAttr: 'relay_storable_io_point', toAttr: 'relay_storable', maxSeconds: 3 },
]

export function loadMovementBaselines(): MovementBaseline[] {
  try {
    const raw = localStorage.getItem(MOVEMENT_STORAGE_KEY)
    if (!raw) return DEFAULT_MOVEMENT_BASELINES
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return DEFAULT_MOVEMENT_BASELINES
    return parsed.filter(
      (m): m is MovementBaseline =>
        typeof m?.fromAttr === 'string' && typeof m?.toAttr === 'string' && typeof m?.maxSeconds === 'number',
    )
  } catch {
    return DEFAULT_MOVEMENT_BASELINES
  }
}

export function saveMovementBaselines(baselines: MovementBaseline[]): void {
  localStorage.setItem(MOVEMENT_STORAGE_KEY, JSON.stringify(baselines))
}

/** null when no manual threshold applies to this attr pair -- callers
 * should fall back to the historical p95 anomaly check (see lib/anomaly.ts)
 * in that case, not treat "no manual threshold" as "always passes". */
export function movementBaselineFor(
  baselines: MovementBaseline[],
  fromAttr: string | null,
  toAttr: string | null,
): number | null {
  const match = baselines.find((b) => b.fromAttr === fromAttr && b.toAttr === toAttr)
  return match?.maxSeconds ?? null
}
