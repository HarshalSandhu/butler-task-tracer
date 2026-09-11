import { useEffect, useMemo, useState } from 'react'
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
import type {
  BenchmarkSubEventResultDto,
  Confidence,
  ForkAdjustmentEventDto,
  LiftEventDto,
  PhaseDto,
  RotationEventDto,
  SavedBenchmarkResultDto,
  TaskEventDto,
} from '../lib/api'
import { fetchBenchmarkResults, saveBenchmarkResult } from '../lib/api'
import { type PhaseBaseline, checkAnomaly, phaseKey } from '../lib/anomaly'
import {
  DEFAULT_MOVEMENT_BASELINES,
  DEFAULT_TASK_TYPE_BASELINES,
  movementBaselineFor,
  type EventBaselines,
  type MovementBaseline,
} from '../lib/baselines'
import { exportTaskTimingToExcel } from '../lib/exportExcel'
import { downloadTaskFullLogs } from '../lib/exportLogs'

/**
 * Gantt/swimlane view of one task's phase-by-phase movement, per
 * PLAN.md "Timeline visualization approach": one row per phase, bar
 * length = duration, color keyed by the grid `attr_tag` (this mapping
 * already exists in the data - relay_storable_io_point, relay_storable,
 * pps_entry_queue, pps, highway, etc.). Non-movement events (fork height
 * changes, tote load, pps_control) render as markers on a thin row below,
 * not as bars, since they're instantaneous actions.
 *
 * Phases are the only rows shown by default -- lift/rotation/fork
 * sub-events are grouped under whichever phase's own time window they
 * fall inside, and stay hidden until that phase is clicked (see
 * expandedPhases below), EXCEPT a phase containing a sub-event that fails
 * its benchmark threshold (see lib/baselines.ts) or a lift/rotation
 * ordering violation auto-expands -- a real problem is never hidden
 * behind a click a user didn't know to make.
 *
 * simultaneousForkLift events (see parsers/lift_events.py) get their own
 * row, rendered as a 3-segment stacked bar: [offset][logged duration]
 * [overlap]. The "overlap" segment is the gap between the log's premature
 * "completed" timestamp and the corrected (real/estimated) completion --
 * rendered in critical red, deliberately extending PAST where the next
 * phase/lift row already starts, so it visually overlaps them exactly the
 * way the fork is physically still settling while the bot has already
 * moved on to its next logged subtask.
 *
 * Recharts has no native Gantt type - this uses the standard
 * offset-bar technique: an invisible bar from 0 to `start`, stacked with
 * a visible bar from `start` to `start + duration`, extended with a third
 * stacked segment for the lift overlap.
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
const LIFT_COLOR = '#d97706' // amber - matches the "fork/lift" semantic used elsewhere
const OVERLAP_COLOR = '#dc2626' // critical red - the corrected/overlapping portion
const ROTATION_COLOR = '#7c3aed' // violet - distinct from both lift (amber) and any attr color
const FORK_ADJUSTMENT_COLOR = '#0d9488' // teal - distinct from lift/rotation/attr colors
const FAIL_COLOR = '#dc2626'

// Compact row pitch so a typical task's full journey (phases + sub-events)
// fits on one screen instead of requiring page-scroll to piece together --
// the original 40px/row pitch pushed a ~25-row trace past 1000px tall. Tall
// enough for a phase row's THREE-line tick (name + "backward" line +
// timestamp, see YAxisTick) without the row above/below overlapping it --
// 30px fit the plain two-line tick but a backward-movement phase's extra
// line overflowed by a few px into its neighbors, which is what actually
// produced the overlapping/unreadable rows reported against a task with
// several return legs expanded at once.
const ROW_HEIGHT = 36
// Hard viewport cap: beyond this, scroll INSIDE the chart's own box so the
// stat cards/legend above stay put as an anchor, rather than scrolling the
// whole page and losing track of which phase you're under.
const MAX_CHART_HEIGHT = 620

function attrColor(attr: string | null): string {
  if (!attr) return DEFAULT_COLOR
  return ATTR_COLORS[attr] ?? DEFAULT_COLOR
}

// Custom Y-axis tick so numbered phase headings (the "1. a -> b" rows) read
// as bold section headers, distinct from the interleaved lift/rotation/fork
// sub-event rows sitting underneath them at the default weight. Phase
// labels also get their exact timestamp on its OWN line below the name --
// putting it on the same line (as a suffix) made the combined string wider
// than the label column, which silently clipped the LEFT/start of the text
// (SVG <text> doesn't wrap or truncate on its own). Phase rows are also
// clickable (expand/collapse their sub-events) -- a leading ▸/▾ glyph and
// the sub-event count show the current state without needing to click to
// find out.
function makeYAxisTick(rowsByLabel: Map<string, Row>, expandedPhases: Set<number>, onTogglePhase: (i: number) => void) {
  return function YAxisTick({ x, y, payload }: { x: number; y: number; payload: { value: string } }) {
    const row = rowsByLabel.get(payload.value)
    const isPhase = row?.kind === 'phase'
    if (isPhase) {
      const expanded = expandedPhases.has(row.phaseIndex)
      const countSuffix = row.subEventCount ? `  (${row.subEventCount})` : ''
      const hasBackward = Boolean(row.isBackwardMovement)
      // Bifurcated on purpose: the transition itself ("N. from -> to") and
      // the backward/return-leg tag render as two separate lines, not one
      // run-on string -- e.g. a chargetask's "charger -> charger_reinit"
      // leg (backing out of the dock) reads as its own heading, with
      // "↩ backward (return leg)" as a distinctly colored line under it,
      // rather than both facts crammed together.
      return (
        <text x={x} y={y} textAnchor="end" onClick={() => onTogglePhase(row.phaseIndex)} style={{ cursor: 'pointer' }}>
          <tspan x={x} dy={hasBackward ? -9 : -3} fill="#f9fafb" fontSize={12} fontWeight={700}>
            {expanded ? '▾ ' : '▸ '}
            {payload.value}
            {countSuffix}
          </tspan>
          {hasBackward && (
            <tspan x={x} dy={12} fill="#fbbf24" fontSize={10} fontWeight={700}>
              ↩ backward (return leg)
            </tspan>
          )}
          <tspan x={x} dy={hasBackward ? 12 : 13} fill="#6b7280" fontSize={9.5} fontWeight={400}>
            {row.timeSuffix}
          </tspan>
        </text>
      )
    }
    return (
      <text x={x} y={y} dy={4} textAnchor="end" fill="#9ca3af" fontSize={11} fontWeight={400}>
        {payload.value}
      </text>
    )
  }
}

function formatExactTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString(undefined, { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

function formatCoordSuffix(coordinate: [number, number] | null): string {
  return coordinate ? ` @ ${coordinate[0].toFixed(1)},${coordinate[1].toFixed(1)}` : ''
}

// Custom tooltip content, replacing recharts' default `formatter` callback.
// The default approach called `formatter` once per STACKED BAR series
// (offset/duration/overlapDuration all share stackId="a") -- since the
// invisible "offset" spacer bar isn't given its own name check, it fell
// into the same branch as "duration" and rendered the identical detail
// text a second time, producing the doubled/overlapping text seen in the
// real UI. Rendering directly from the row here (once) removes that
// duplication at the source, and wraps long detail text so it's never
// clipped at the viewport edge.
function SwimlaneTooltip({ active, payload, label }: { active?: boolean; payload?: unknown[]; label?: string }) {
  if (!active || !payload || payload.length === 0) return null
  const row = (payload[0] as { payload: Row }).payload
  return (
    <div
      style={{
        backgroundColor: '#1f2937',
        border: '1px solid #374151',
        color: '#e5e7eb',
        padding: '8px 10px',
        borderRadius: 4,
        maxWidth: 380,
      }}
    >
      <div style={{ marginBottom: 4 }}>
        {label} - starts {formatExactTime(row.startTimeIso)}, ends {formatExactTime(row.endTimeIso)}
      </div>
      <div>{row.duration.toFixed(2)}s{row.multipleOfP95 ? ` (${row.multipleOfP95.toFixed(1)}x p95)` : ''}</div>
      <div style={{ color: '#9ca3af', whiteSpace: 'normal', wordBreak: 'break-word' }}>
        {row.tooltipExtra ?? row.label}
      </div>
      {row.overlapDuration > 0 && (
        <div style={{ color: '#f87171', marginTop: 4 }}>+{row.overlapDuration.toFixed(2)}s overlap</div>
      )}
    </div>
  )
}

export interface Row {
  key: string
  label: string
  offset: number
  duration: number
  overlapDuration: number
  attr: string | null
  fromAttr: string | null
  // WARNING: startIso is NOT consistently "the start" across row kinds --
  // for phase/rotation rows it's actually the ARRIVAL/completion instant
  // (kept only because other code -- the Y-axis tick's timeSuffix, the
  // minor-rotation summary -- already depends on this exact value), while
  // for lift/fork rows it genuinely is the start (order_sent_at/
  // started_at). Never derive "end = startIso + duration" from this field
  // -- use startTimeIso/endTimeIso below instead, which are unambiguous
  // and correct for every row kind (computed directly from offset/
  // duration, which are always real elapsed-seconds-since-task-start).
  startIso: string
  // Unambiguous real start/end timestamps, correct for every row kind --
  // used by the tooltip and the Excel export instead of the
  // kind-dependent startIso above.
  startTimeIso: string
  endTimeIso: string
  isAnomalous: boolean
  multipleOfP95: number | null
  kind: 'phase' | 'lift' | 'rotation' | 'fork'
  correctionMethod?: LiftEventDto['correction_method']
  tooltipExtra?: string
  // Phase rows only: exact arrival timestamp, rendered on its own line
  // below the name by the custom Y-axis tick (see makeYAxisTick).
  timeSuffix?: string
  // Which phase (by index into the `phases` prop) this row belongs to --
  // for phase rows, their own index; for sub-event rows, whichever phase's
  // time window contains them (see _assignPhaseIndex). Drives the
  // collapse/expand grouping.
  phaseIndex: number
  // Phase rows only: how many sub-event rows are grouped under it.
  subEventCount?: number
  // Lift/rotation/fork rows only: benchmark result against the manually
  // configured threshold (see lib/baselines.ts) -- null for phase rows,
  // which use the separate p95-based isAnomalous/multipleOfP95 mechanism.
  passFail: 'pass' | 'fail' | null
  // Rotation rows only: this rotation's own completion landed before an
  // overlapping lift event's real (corrected) completion -- the bot
  // finished turning while the fork was still physically moving.
  sequenceViolation?: boolean
  // Phase rows only: this phase's destination is exactly where the
  // PREVIOUS phase departed from (the bot went A->B, this leg is B->A) --
  // rendered as its own distinctly-colored line (see makeYAxisTick),
  // deliberately NOT folded into `label` as a suffix, so the transition
  // itself and the backward/return-leg fact stay two separate, clearly
  // delineated pieces (e.g. a chargetask's "charger -> charger_reinit"
  // leg backing out of the dock).
  isBackwardMovement?: boolean
  // The original DTO this row was built from (undefined for phase rows,
  // which have no single DTO -- they're derived from trace.events).
  // Carried through so exportExcel.ts can emit every underlying field
  // (heights, coordinates, correction method, confidence, etc.) as its
  // own column, instead of re-parsing the human-readable label string.
  raw?: LiftEventDto | RotationEventDto | ForkAdjustmentEventDto
  // Phase rows only: attribution confidence (see PhaseDto) -- exact
  // (a real goto_barcode_completed line named this task directly) vs
  // heuristic (recovered via the generic-movement fallback).
  confidence?: Confidence
}

// Real start/end timestamps for a row, derived uniformly from `offset`/
// `duration` (always correctly computed as real elapsed-seconds-since-
// task-start at every row's construction site, unlike the ambiguous
// `startIso` field -- see Row's own docstring above).
function timeRangeIso(taskStart: number, offset: number, duration: number): { startTimeIso: string; endTimeIso: string } {
  return {
    startTimeIso: new Date(taskStart + offset * 1000).toISOString(),
    endTimeIso: new Date(taskStart + (offset + duration) * 1000).toISOString(),
  }
}

function assignPhaseIndex(absoluteMs: number, phaseIntervals: { startMs: number; endMs: number }[]): number {
  for (let i = 0; i < phaseIntervals.length; i++) {
    if (absoluteMs >= phaseIntervals[i].startMs && absoluteMs < phaseIntervals[i].endMs) return i
  }
  // Not inside any phase's own window -- attach to the nearest one instead
  // of dropping it (before the first phase started, or after the last
  // one ended, both real edge cases near a task's start/end).
  let nearest = 0
  let bestDelta = Infinity
  phaseIntervals.forEach((iv, i) => {
    const delta = absoluteMs < iv.startMs ? iv.startMs - absoluteMs : absoluteMs >= iv.endMs ? absoluteMs - iv.endMs : 0
    if (delta < bestDelta) {
      bestDelta = delta
      nearest = i
    }
  })
  return nearest
}

export function TaskSwimlane({
  phases,
  events,
  liftEvents = [],
  rotationEvents = [],
  forkAdjustmentEvents = [],
  baselines,
  eventBaselines = DEFAULT_TASK_TYPE_BASELINES.relay_pps_task,
  movementBaselines = DEFAULT_MOVEMENT_BASELINES,
  taskId,
  taskType,
  butlerIp,
}: {
  phases: PhaseDto[]
  events: TaskEventDto[]
  liftEvents?: LiftEventDto[]
  rotationEvents?: RotationEventDto[]
  forkAdjustmentEvents?: ForkAdjustmentEventDto[]
  baselines?: Map<string, PhaseBaseline>
  eventBaselines?: EventBaselines
  // Manual per-phase-movement thresholds (see lib/baselines.ts) -- separate
  // from the historical p95 anomaly check (`baselines` above), which needs
  // >=5 prior samples and flags relative drift instead of an absolute
  // ceiling.
  movementBaselines?: MovementBaseline[]
  // Needed only for the explicit "Save benchmark result"/"View saved
  // results" actions below (see api/routes.py's benchmark-result
  // endpoints) -- omit to hide those controls entirely.
  taskId?: string | null
  taskType?: string | null
  butlerIp?: string
}) {
  // The journey's own t=0 -- the FIRST phase's own start (arrival minus its
  // own duration), not that phase's arrival instant. Anchoring to arrival
  // made the first phase (and anything logged during its travel) render at
  // a negative offset, pushing the chart's real content well past a visible
  // "0s" and leaving a wide dead zone of empty axis before anything starts.
  const taskStart =
    phases.length > 0
      ? new Date(phases[0].timestamp).getTime() - phases[0].duration_seconds * 1000
      : 0

  const { phaseRows, subEventRows } = useMemo(() => {
    const phaseIntervals = phases.map((p) => {
      const endMs = new Date(p.timestamp).getTime()
      return { startMs: endMs - p.duration_seconds * 1000, endMs }
    })

    // Coordinate suffixes are only worth their width when two phases
    // actually share the same attr-pair but are physically different stops
    // (confirmed real for VTM) -- appending them to EVERY phase regardless
    // made routine labels like "relay_storable_io_point @ 14.0,44.0 ->
    // relay_storable @ 12.0,44.0" long enough to overflow the Y-axis
    // column and get left-clipped (see YAxisTick's comment on this exact
    // failure mode), which read as garbled/overlapping text once several
    // such phases were expanded at once.
    const attrPairCounts = new Map<string, number>()
    phases.forEach((p) => {
      const key = `${p.from_attr ?? '?'}->${p.to_attr ?? '?'}`
      attrPairCounts.set(key, (attrPairCounts.get(key) ?? 0) + 1)
    })

    const phaseRows: Row[] = phases.map((p, i) => {
      const { startMs, endMs } = phaseIntervals[i]
      const offset = (startMs - taskStart) / 1000
      const anomaly = baselines
        ? checkAnomaly(
            { fromAttr: p.from_attr, toAttr: p.to_attr, durationSeconds: p.duration_seconds },
            baselines,
          )
        : { isAnomalous: false, multipleOfP95: null }
      // Only shown when this attr-pair is genuinely ambiguous (appears more
      // than once) -- see attrPairCounts above.
      const isAmbiguousPair = (attrPairCounts.get(`${p.from_attr ?? '?'}->${p.to_attr ?? '?'}`) ?? 0) > 1
      const fromCoordSuffix = isAmbiguousPair ? formatCoordSuffix(p.from_coordinate) : ''
      const toCoordSuffix = isAmbiguousPair ? formatCoordSuffix(p.to_coordinate) : ''
      // A phase whose destination is exactly where the PREVIOUS phase
      // departed FROM is a return/backward leg (the bot went A->B then
      // B->A) -- coordinate-based when available (exact), falling back to
      // attr-string comparison only if a coordinate is missing (a stale
      // cached trace from before this field existed).
      const prev = i > 0 ? phases[i - 1] : null
      const isBackward =
        prev !== null &&
        (p.to_coordinate && prev.from_coordinate
          ? p.to_coordinate[0] === prev.from_coordinate[0] && p.to_coordinate[1] === prev.from_coordinate[1]
          : p.to_attr === prev.from_attr)
      const duration = (endMs - startMs) / 1000
      // A manual movement threshold is a separate, absolute-ceiling check
      // from the historical p95 anomaly flag above -- applies immediately
      // (no prior-sample requirement) but only to attr pairs the user has
      // actually configured a number for (see lib/baselines.ts).
      const movementThreshold = movementBaselineFor(movementBaselines, p.from_attr, p.to_attr)
      const passFail: Row['passFail'] = movementThreshold != null ? (duration <= movementThreshold ? 'pass' : 'fail') : null
      const badge = passFail === 'fail' ? '❌ ' : passFail === 'pass' ? '✅ ' : ''
      return {
        key: `phase-${i}`,
        label: `${badge}${i + 1}. ${p.from_attr ?? '?'}${fromCoordSuffix} -> ${p.to_attr}${toCoordSuffix}`,
        timeSuffix: formatExactTime(p.timestamp),
        offset,
        duration,
        overlapDuration: 0,
        attr: p.to_attr,
        fromAttr: p.from_attr,
        startIso: p.timestamp,
        ...timeRangeIso(taskStart, offset, duration),
        isAnomalous: anomaly.isAnomalous,
        multipleOfP95: anomaly.multipleOfP95,
        kind: 'phase' as const,
        phaseIndex: i,
        passFail,
        confidence: p.confidence,
        isBackwardMovement: isBackward,
        tooltipExtra:
          [
            passFail === 'fail'
              ? `FAIL: took ${duration.toFixed(2)}s, threshold is ${movementThreshold}s`
              : null,
            isBackward
              ? `backward movement -- the bot returned to ${p.to_attr}${toCoordSuffix}, exactly where the previous phase departed from`
              : null,
          ]
            .filter(Boolean)
            .join(' -- ') || undefined,
      }
    })

    const liftIntervals: { startMs: number; realEndMs: number }[] = []

    const liftRows: Row[] = liftEvents.map((le, i) => {
      const loggedMs = new Date(le.logged_complete_at).getTime()
      const startMs = le.order_sent_at ? new Date(le.order_sent_at).getTime() : loggedMs
      const offset = (startMs - taskStart) / 1000
      const loggedDuration = Math.max(0.05, (loggedMs - startMs) / 1000)
      const correctedMs = le.corrected_complete_at ? new Date(le.corrected_complete_at).getTime() : null
      const overlapDuration = correctedMs ? Math.max(0, (correctedMs - loggedMs) / 1000) : 0
      const realEndMs = correctedMs ?? loggedMs
      liftIntervals.push({ startMs, realEndMs })
      const totalSeconds = (realEndMs - startMs) / 1000
      const passFail: Row['passFail'] = totalSeconds <= eventBaselines.liftMaxSeconds ? 'pass' : 'fail'
      const badge = passFail === 'fail' ? '❌ ' : '✅ '
      const methodLabel =
        le.correction_method === 'telemetry'
          ? 'confirmed via reported lift height'
          : le.correction_method === 'estimated_buffer'
            ? 'estimated from computed travel time'
            : 'no correction available'
      const heightSuffix = le.target_height_mm != null ? ` -> ${le.target_height_mm}mm` : ''
      const coordSuffix = formatCoordSuffix(le.coordinate)
      const label = le.context_label
        ? `${badge}⚡ ${le.context_label} (bot ${le.bot_id}${heightSuffix}${coordSuffix})`
        : `${badge}⚡ simultaneousForkLift (bot ${le.bot_id}${heightSuffix}${coordSuffix})`
      const failNote =
        passFail === 'fail'
          ? ` -- FAIL: took ${totalSeconds.toFixed(2)}s, threshold is ${eventBaselines.liftMaxSeconds}s`
          : ''
      return {
        key: `lift-${i}`,
        label,
        offset,
        duration: loggedDuration,
        overlapDuration,
        attr: null,
        fromAttr: null,
        startIso: le.order_sent_at ?? le.logged_complete_at,
        // The real, full physical span includes the overlap segment (the
        // fork settling after the logged-instant "complete") -- using
        // just loggedDuration here would under-report the end time by
        // however long the fork was still actually moving.
        ...timeRangeIso(taskStart, offset, loggedDuration + overlapDuration),
        isAnomalous: overlapDuration > 0,
        multipleOfP95: null,
        kind: 'lift' as const,
        correctionMethod: le.correction_method,
        phaseIndex: assignPhaseIndex(startMs, phaseIntervals),
        passFail,
        raw: le,
        tooltipExtra:
          (overlapDuration > 0
            ? `logged complete instantly, but ${methodLabel}: fork still settling for another ${overlapDuration.toFixed(2)}s -- overlaps whatever's logged next`
            : methodLabel) + failNote,
      }
    })

    // Only "major" rotations (near a key waypoint - see event_context.py)
    // get their own row; ordinary in-transit turns are summarized separately
    // below instead of cluttering the chart with one bar each.
    const rotationRows: Row[] = rotationEvents
      .filter((re) => re.significance === 'major')
      .map((re, i) => {
        const endMs = new Date(re.timestamp).getTime()
        const durationSeconds = re.duration_ms / 1000
        const startMs = endMs - re.duration_ms
        const offset = (startMs - taskStart) / 1000
        const coordSuffix = formatCoordSuffix(re.coordinate)
        const passFail: Row['passFail'] = durationSeconds <= eventBaselines.rotationMaxSeconds ? 'pass' : 'fail'
        // The rule: a simultaneous lift should complete before the
        // rotation completes -- flagged when this rotation's own
        // completion (endMs) lands before an overlapping lift's real
        // completion, i.e. the bot finished turning while the fork was
        // still physically moving. "Overlapping" means the two events'
        // time spans actually intersect, not just landing anywhere near
        // each other.
        const sequenceViolation = liftIntervals.some(
          (lift) => startMs < lift.realEndMs && lift.startMs < endMs && endMs < lift.realEndMs,
        )
        const badge = sequenceViolation ? '⚠️ ' : passFail === 'fail' ? '❌ ' : '✅ '
        const failNote = passFail === 'fail' ? ` -- FAIL: took ${durationSeconds.toFixed(2)}s, threshold is ${eventBaselines.rotationMaxSeconds}s` : ''
        const violationNote = sequenceViolation
          ? ' -- rotation completed BEFORE the overlapping simultaneous lift finished settling'
          : ''
        return {
          key: `rotation-${i}`,
          label: `${badge}↻ ${re.context_label ?? 'rotation'} (bot ${re.bot_id}${coordSuffix})`,
          offset,
          duration: Math.max(0.05, durationSeconds),
          overlapDuration: 0,
          attr: null,
          fromAttr: null,
          startIso: re.timestamp,
          ...timeRangeIso(taskStart, offset, Math.max(0.05, durationSeconds)),
          isAnomalous: false,
          multipleOfP95: null,
          kind: 'rotation' as const,
          phaseIndex: assignPhaseIndex(startMs, phaseIntervals),
          passFail,
          sequenceViolation,
          raw: re,
          tooltipExtra:
            (re.method === 'telemetry'
              ? 'ground truth: the AGV\'s own reported heading (agvPosition.theta) actually changed here'
              : 'estimated from the bot\'s planned-path log, not a precise wall-clock timestamp - ' +
                'see rotation_events.py') + failNote + violationNote,
        }
      })

    // Fork adjustments not already shown as a lift event -- e.g. raising to
    // approach a tote, or the PPS handoff height. "pick"/"drop" specifically
    // at relay_storable, generic "lift up/down @ <attr>" elsewhere -- see
    // event_context.py's label_fork_adjustment.
    const forkRows: Row[] = forkAdjustmentEvents.map((fe, i) => {
      const endMs = new Date(fe.timestamp).getTime()
      // started_at is real evidence the fork was already moving before it
      // settled at timestamp (see lift_events.py's _merged_transitions) --
      // rendering the bar across that real span, rather than a fixed
      // instant marker at timestamp alone, is what shows a rise can begin
      // *during* the tail of the previous movement phase.
      const startMs = fe.started_at ? new Date(fe.started_at).getTime() : endMs - 50
      const offset = (startMs - taskStart) / 1000
      const duration = Math.max(0.05, (endMs - startMs) / 1000)
      const passFail: Row['passFail'] = duration <= eventBaselines.forkMaxSeconds ? 'pass' : 'fail'
      const badge = passFail === 'fail' ? '❌ ' : '✅ '
      const icon = fe.direction === 'up' ? '▲' : '▼'
      const coordSuffix = formatCoordSuffix(fe.coordinate)
      const label = `${badge}${icon} ${fe.label ?? (fe.direction === 'up' ? 'lift up' : 'lift down')} (bot ${fe.bot_id} -> ${Math.round(fe.to_height_mm)}mm${coordSuffix})`
      const failNote = passFail === 'fail' ? ` -- FAIL: took ${duration.toFixed(2)}s, threshold is ${eventBaselines.forkMaxSeconds}s` : ''
      return {
        key: `fork-${i}`,
        label,
        offset,
        duration,
        overlapDuration: 0,
        attr: null,
        fromAttr: null,
        startIso: fe.started_at ?? fe.timestamp,
        ...timeRangeIso(taskStart, offset, duration),
        isAnomalous: false,
        multipleOfP95: null,
        kind: 'fork' as const,
        phaseIndex: assignPhaseIndex(startMs, phaseIntervals),
        passFail,
        raw: fe,
        tooltipExtra: `fork height ${Math.round(fe.from_height_mm)}mm -> ${Math.round(fe.to_height_mm)}mm, settled ${formatExactTime(fe.timestamp)} (from AGV telemetry)${failNote}`,
      }
    })

    const subEventRows = [...liftRows, ...rotationRows, ...forkRows].sort((a, b) => a.offset - b.offset)
    subEventRows.forEach((r) => {
      phaseRows[r.phaseIndex].subEventCount = (phaseRows[r.phaseIndex].subEventCount ?? 0) + 1
    })
    return { phaseRows, subEventRows }
  }, [phases, liftEvents, rotationEvents, forkAdjustmentEvents, taskStart, baselines, eventBaselines, movementBaselines])

  // Phases containing a failing sub-event (or a lift/rotation ordering
  // violation) auto-expand -- collapsing sub-events by default must never
  // hide a real problem behind a click the user didn't know to make.
  const phasesWithFailures = useMemo(() => {
    const set = new Set<number>()
    subEventRows.forEach((r) => {
      if (r.passFail === 'fail' || r.sequenceViolation) set.add(r.phaseIndex)
    })
    return set
  }, [subEventRows])

  const [expandedPhases, setExpandedPhases] = useState<Set<number>>(() => new Set(phasesWithFailures))
  useEffect(() => {
    setExpandedPhases((prev) => {
      const merged = new Set(prev)
      let changed = false
      phasesWithFailures.forEach((i) => {
        if (!merged.has(i)) {
          merged.add(i)
          changed = true
        }
      })
      return changed ? merged : prev
    })
  }, [phasesWithFailures])

  const togglePhase = (index: number) => {
    setExpandedPhases((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const rows: Row[] = useMemo(
    () =>
      [...phaseRows, ...subEventRows.filter((r) => expandedPhases.has(r.phaseIndex))].sort(
        (a, b) => a.offset - b.offset,
      ),
    [phaseRows, subEventRows, expandedPhases],
  )

  // Explicit, user-triggered persistence -- never saved/fetched
  // automatically just because this task was viewed (see
  // api/routes.py's BenchmarkResultRow docstring).
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [history, setHistory] = useState<SavedBenchmarkResultDto[] | null>(null)
  const [historyState, setHistoryState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [exportState, setExportState] = useState<'idle' | 'exporting' | 'error'>('idle')
  const [logsExportState, setLogsExportState] = useState<'idle' | 'exporting' | 'error'>('idle')

  // TaskSwimlane stays mounted across different tasks (same route, new
  // data) -- without this, a "saved"/history state from the PREVIOUS
  // task would incorrectly linger onto the next one.
  useEffect(() => {
    setSaveState('idle')
    setHistory(null)
    setHistoryState('idle')
    setExportState('idle')
    setLogsExportState('idle')
  }, [taskId])

  const handleSaveBenchmarkResult = async () => {
    if (!taskId || !butlerIp) return
    setSaveState('saving')
    try {
      const results: BenchmarkSubEventResultDto[] = subEventRows.map((r) => ({
        kind: r.kind as 'lift' | 'rotation' | 'fork',
        label: r.label,
        duration_seconds: r.duration + r.overlapDuration,
        threshold_seconds:
          r.kind === 'lift'
            ? eventBaselines.liftMaxSeconds
            : r.kind === 'rotation'
              ? eventBaselines.rotationMaxSeconds
              : eventBaselines.forkMaxSeconds,
        passed: r.passFail === 'pass',
        sequence_violation: Boolean(r.sequenceViolation),
      }))
      await saveBenchmarkResult({ taskId, taskType: taskType ?? null, butlerIp, thresholds: eventBaselines, results })
      setSaveState('saved')
      if (history !== null) {
        // Already-open history panel should reflect the just-saved run
        // without requiring a second explicit fetch click.
        const refreshed = await fetchBenchmarkResults(taskId)
        setHistory(refreshed.results)
      }
    } catch {
      setSaveState('error')
    }
  }

  const handleToggleHistory = async () => {
    if (!taskId) return
    if (history !== null) {
      setHistory(null)
      return
    }
    setHistoryState('loading')
    try {
      const fetched = await fetchBenchmarkResults(taskId)
      setHistory(fetched.results)
      setHistoryState('idle')
    } catch {
      setHistoryState('error')
    }
  }

  const handleExportToExcel = async () => {
    if (!taskId || !butlerIp) return
    setExportState('exporting')
    try {
      await exportTaskTimingToExcel({ taskId, taskType: taskType ?? null, butlerIp, phaseRows, subEventRows })
      setExportState('idle')
    } catch {
      setExportState('error')
    }
  }

  const handleDownloadFullLogs = async () => {
    if (!taskId || !butlerIp) return
    setLogsExportState('exporting')
    try {
      await downloadTaskFullLogs({ taskId, butlerIp })
      setLogsExportState('idle')
    } catch {
      setLogsExportState('error')
    }
  }

  const rowsByLabel = useMemo(() => new Map(rows.map((r) => [r.label, r])), [rows])
  const yAxisTick = useMemo(
    () => makeYAxisTick(rowsByLabel, expandedPhases, togglePhase),
    [rowsByLabel, expandedPhases],
  )

  const minorRotations = rotationEvents.filter((re) => re.significance === 'minor')
  const minorRotationSummary =
    minorRotations.length > 0
      ? {
          count: minorRotations.length,
          totalSeconds: minorRotations.reduce((sum, re) => sum + re.duration_ms / 1000, 0),
        }
      : null

  const nonMovementEvents = events.filter((e) => !e.attr_tag)

  if (rows.length === 0) {
    return (
      <p className="text-gray-400 text-sm">
        No movement phases, lift events, or rotation events found for this task.
      </p>
    )
  }

  const naturalHeight = Math.max(200, rows.length * ROW_HEIGHT + 40)
  const isCapped = naturalHeight > MAX_CHART_HEIGHT
  const totalSubEvents = subEventRows.length
  const failCount = subEventRows.filter((r) => r.passFail === 'fail' || r.sequenceViolation).length

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-gray-500">
          {phaseRows.length} phase{phaseRows.length === 1 ? '' : 's'} shown -- click a phase to show/hide its{' '}
          {totalSubEvents} sub-event{totalSubEvents === 1 ? '' : 's'}.
          {failCount > 0 && (
            <span className="text-red-400"> {failCount} failing sub-event{failCount === 1 ? '' : 's'} auto-expanded.</span>
          )}
          {isCapped && ' Scroll inside the chart below to see the rest of the journey.'}
        </p>
        {taskId && butlerIp && (
          <div className="flex items-center gap-2 text-[11px]">
            <button
              type="button"
              onClick={handleSaveBenchmarkResult}
              disabled={saveState === 'saving'}
              className="text-gray-300 hover:text-gray-100 disabled:text-gray-500 border border-gray-700 rounded px-2 py-1 transition-colors"
            >
              💾 {saveState === 'saving' ? 'Saving...' : 'Save benchmark result'}
            </button>
            {saveState === 'saved' && <span className="text-green-400">saved</span>}
            {saveState === 'error' && <span className="text-red-400">save failed</span>}
            <button
              type="button"
              onClick={handleToggleHistory}
              className="text-gray-300 hover:text-gray-100 border border-gray-700 rounded px-2 py-1 transition-colors"
            >
              📋 {history !== null ? 'Hide' : 'View'} saved results
            </button>
            <button
              type="button"
              onClick={handleExportToExcel}
              disabled={exportState === 'exporting'}
              className="text-gray-300 hover:text-gray-100 disabled:text-gray-500 border border-gray-700 rounded px-2 py-1 transition-colors"
            >
              📥 {exportState === 'exporting' ? 'Exporting...' : 'Export to Excel'}
            </button>
            {exportState === 'error' && <span className="text-red-400">export failed</span>}
            <button
              type="button"
              onClick={handleDownloadFullLogs}
              disabled={logsExportState === 'exporting'}
              title="Every raw log line in this task's own time window, first to last -- not filtered to task_id, butler_id, or any known marker pattern"
              className="text-gray-300 hover:text-gray-100 disabled:text-gray-500 border border-gray-700 rounded px-2 py-1 transition-colors"
            >
              🗒️ {logsExportState === 'exporting' ? 'Fetching all logs...' : 'Download all logs'}
            </button>
            {logsExportState === 'error' && <span className="text-red-400">fetch failed</span>}
          </div>
        )}
      </div>

      {historyState === 'loading' && <p className="text-[11px] text-gray-500">Loading saved results...</p>}
      {historyState === 'error' && <p className="text-[11px] text-red-400">Could not load saved results.</p>}
      {history !== null && (
        <div className="border border-gray-700 rounded-md overflow-x-auto">
          {history.length === 0 ? (
            <p className="text-[11px] text-gray-500 p-2">No saved results yet for this task.</p>
          ) : (
            <table className="w-full text-[11px]">
              <thead className="bg-gray-800 text-gray-400">
                <tr>
                  <th className="text-left px-2 py-1">Saved at</th>
                  <th className="text-left px-2 py-1">Thresholds (lift/rotation/fork, s)</th>
                  <th className="text-left px-2 py-1">Pass</th>
                  <th className="text-left px-2 py-1">Fail</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.id} className="border-t border-gray-700 text-gray-300">
                    <td className="px-2 py-1 font-mono">{formatExactTime(h.recorded_at)}</td>
                    <td className="px-2 py-1 font-mono">
                      {h.thresholds.liftMaxSeconds}/{h.thresholds.rotationMaxSeconds}/{h.thresholds.forkMaxSeconds}
                    </td>
                    <td className="px-2 py-1 text-green-400">{h.pass_count}</td>
                    <td className="px-2 py-1 text-red-400">{h.fail_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <div
        style={isCapped ? { maxHeight: MAX_CHART_HEIGHT, overflowY: 'auto' } : undefined}
        className={isCapped ? 'border border-gray-800 rounded-md' : undefined}
      >
        <ResponsiveContainer width="100%" height={naturalHeight}>
          <BarChart data={rows} layout="vertical" margin={{ top: 8, left: 24, right: 24 }} barCategoryGap={4}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#374151" />
            <XAxis
              type="number"
              unit="s"
              tick={{ fill: '#9ca3af' }}
              stroke="#4b5563"
              label={{ value: 'Seconds since task start', position: 'insideBottom', offset: -5, fill: '#9ca3af' }}
            />
            <YAxis type="category" dataKey="label" width={400} tick={yAxisTick} stroke="#4b5563" />
          {/* Recharts' default BarChart cursor fills the ENTIRE category
              row width with a stark, opaque highlight -- with rows packed
              at ROW_HEIGHT=30px this reads as an ugly wide gray block
              cutting across neighboring rows. A subtle, low-opacity fill
              keeps the "which row am I hovering" affordance without the
              visual clash. */}
          <Tooltip content={<SwimlaneTooltip />} cursor={{ fill: '#ffffff', fillOpacity: 0.04 }} />
          {/* invisible spacer bar positions every row at its real time offset */}
          <Bar dataKey="offset" stackId="a" fill="transparent" isAnimationActive={false} />
          {/* the "as logged" duration -- attr color for phases, amber for lift events */}
          <Bar dataKey="duration" stackId="a" isAnimationActive={false} radius={2}>
            {rows.map((row, i) => {
              // row.attr is always set (non-null) for phase rows -- lift rows
              // take the row.key branch instead, so this assertion never
              // fires on an actually-null value.
              const cellKey = row.kind === 'phase' ? phaseKey(row.fromAttr, row.attr!) : row.key
              const fill =
                row.kind === 'lift'
                  ? LIFT_COLOR
                  : row.kind === 'rotation'
                    ? ROTATION_COLOR
                    : row.kind === 'fork'
                      ? FORK_ADJUSTMENT_COLOR
                      : attrColor(row.attr)
              const failStroke = row.passFail === 'fail' || row.sequenceViolation
              const anomalousStroke = row.isAnomalous && row.kind === 'phase'
              return (
                <Cell
                  key={cellKey + i}
                  fill={fill}
                  stroke={failStroke ? FAIL_COLOR : anomalousStroke ? '#dc2626' : undefined}
                  strokeWidth={failStroke || anomalousStroke ? 3 : 0}
                />
              )
            })}
          </Bar>
          {/* the overlap segment: only lift rows with a corrected completion
              past the logged one have any width here -- everything else is 0,
              rendering nothing. This is what makes the lift event visually
              extend into/over whatever's plotted immediately after it. */}
          <Bar dataKey="overlapDuration" stackId="a" isAnimationActive={false} radius={2}>
            {rows.map((row, i) => (
              <Cell
                key={`overlap-${row.key}-${i}`}
                fill={OVERLAP_COLOR}
                fillOpacity={0.55}
                stroke={OVERLAP_COLOR}
                strokeDasharray="3 2"
                strokeWidth={row.overlapDuration > 0 ? 1.5 : 0}
              />
            ))}
          </Bar>
        </BarChart>
        </ResponsiveContainer>
      </div>

      {liftEvents.some((le) => le.correction_method) && (
        <div className="flex flex-wrap gap-3 text-[11px] text-gray-400 items-center">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: LIFT_COLOR }} />
            simultaneousForkLift (as logged)
          </span>
          <span className="inline-flex items-center gap-1">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ background: OVERLAP_COLOR, opacity: 0.55, border: `1px dashed ${OVERLAP_COLOR}` }}
            />
            corrected overlap (fork still settling)
          </span>
        </div>
      )}

      {rotationEvents.length > 0 && (
        <div className="flex flex-wrap gap-3 text-[11px] text-gray-400 items-center">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: ROTATION_COLOR }} />
            in-place rotation near a key waypoint (estimated, see tooltip)
          </span>
          {minorRotationSummary && (
            <span title="Ordinary in-transit turns away from relay_storable_io_point/pps -- not shown individually">
              + {minorRotationSummary.count} more rotation{minorRotationSummary.count === 1 ? '' : 's'} in
              transit ({minorRotationSummary.totalSeconds.toFixed(1)}s total)
            </span>
          )}
        </div>
      )}

      {forkAdjustmentEvents.length > 0 && (
        <div className="flex flex-wrap gap-3 text-[11px] text-gray-400 items-center">
          <span className="inline-flex items-center gap-1">
            <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: FORK_ADJUSTMENT_COLOR }} />
            fork adjustment (pick/drop/lift, from AGV telemetry)
          </span>
          <span>✅/❌ = benchmark pass/fail against manual thresholds; ⚠️ = rotation finished before an overlapping lift settled</span>
        </div>
      )}

      {nonMovementEvents.length > 0 && (
        <div className="border-t border-gray-700 pt-2">
          <p className="text-xs text-gray-400 mb-1">Non-movement actions</p>
          <div className="flex flex-wrap gap-2">
            {nonMovementEvents.map((e, i) => (
              <span
                key={i}
                title={`${e.raw_line}\n${formatExactTime(e.timestamp)}`}
                className="inline-flex items-center gap-1 text-xs bg-gray-800 text-gray-200 rounded px-2 py-1"
              >
                <span className="inline-block w-2 h-2 rotate-45 bg-gray-400" />
                {e.phase_label ?? e.function}
                <span className="text-gray-500">{formatExactTime(e.timestamp)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
