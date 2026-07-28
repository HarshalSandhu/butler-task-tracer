/**
 * p50/p95 baseline computation + anomaly flagging, shared between the
 * single-task deep-dive view (flag a bar red) and the batch view (filter
 * column "show only tasks with >=1 flagged phase").
 *
 * See PLAN.md "Anomaly flagging" - a phase is flagged when its duration
 * exceeds 2x the historical p95 for that same phase key (from_attr ->
 * to_attr pair), computed from whatever set of phase durations is passed
 * in (typically all phases of that kind seen in a batch/window query).
 */

export interface PhaseDuration {
  fromAttr: string | null
  toAttr: string
  durationSeconds: number
}

export interface PhaseBaseline {
  phaseKey: string
  p50: number
  p95: number
  sampleCount: number
}

export const ANOMALY_THRESHOLD_MULTIPLE = 2

export function phaseKey(fromAttr: string | null, toAttr: string): string {
  return `${fromAttr ?? '?'}->${toAttr}`
}

function percentile(sortedValues: number[], p: number): number {
  if (sortedValues.length === 0) return NaN
  const idx = Math.min(
    sortedValues.length - 1,
    Math.max(0, Math.ceil((p / 100) * sortedValues.length) - 1),
  )
  return sortedValues[idx]
}

/** Groups `durations` by phaseKey and computes p50/p95 per group. */
export function computeBaselines(durations: PhaseDuration[]): Map<string, PhaseBaseline> {
  const byKey = new Map<string, number[]>()
  for (const d of durations) {
    const key = phaseKey(d.fromAttr, d.toAttr)
    const arr = byKey.get(key) ?? []
    arr.push(d.durationSeconds)
    byKey.set(key, arr)
  }

  const baselines = new Map<string, PhaseBaseline>()
  for (const [key, values] of byKey) {
    const sorted = [...values].sort((a, b) => a - b)
    baselines.set(key, {
      phaseKey: key,
      p50: percentile(sorted, 50),
      p95: percentile(sorted, 95),
      sampleCount: sorted.length,
    })
  }
  return baselines
}

export interface AnomalyResult {
  isAnomalous: boolean
  multipleOfP95: number | null
  baseline: PhaseBaseline | null
}

/**
 * Flags a single phase duration against a precomputed baseline map. Never
 * flags anything if the baseline has too few samples to be meaningful
 * (fewer than 5) - a single prior data point isn't a real p95.
 */
export function checkAnomaly(
  duration: PhaseDuration,
  baselines: Map<string, PhaseBaseline>,
  minSamplesForBaseline = 5,
): AnomalyResult {
  const key = phaseKey(duration.fromAttr, duration.toAttr)
  const baseline = baselines.get(key) ?? null

  if (!baseline || baseline.sampleCount < minSamplesForBaseline || baseline.p95 <= 0) {
    return { isAnomalous: false, multipleOfP95: null, baseline }
  }

  const multiple = duration.durationSeconds / baseline.p95
  return {
    isAnomalous: multiple >= ANOMALY_THRESHOLD_MULTIPLE,
    multipleOfP95: multiple,
    baseline,
  }
}
