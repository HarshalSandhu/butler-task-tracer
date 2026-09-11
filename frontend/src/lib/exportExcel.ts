import type { Row } from '../components/TaskSwimlane'
import type { ForkAdjustmentEventDto, LiftEventDto, RotationEventDto } from './api'

const HEADERS = [
  'Phase #',
  'Route (From -> To)',
  'Sub-event kind',
  'Sub-event label / context',
  'Sub-event start',
  'Sub-event end',
  'Sub-event duration (s)',
  'L1 baseline (s)',
  'Overlap (s)',
  'From height (mm)',
  'To height (mm)',
  'Pass/Fail',
  'Phase start',
  'Phase end',
  'Phase duration (s)',
]
const COLUMN_WIDTHS = [8, 30, 12, 36, 20, 20, 17, 13, 11, 14, 13, 9, 20, 20, 15]
// Phase-identifying columns merged vertically across a phase's sub-event
// rows -- split into a front block (identity) and a tail block (timing),
// with the sub-event-specific columns sandwiched in between.
const FRONT_PHASE_COLUMNS = [1, 2]
const TAIL_PHASE_COLUMNS = [13, 14, 15]

// Light, print-friendly palette -- the previous scheme filled alternating
// rows with a dark slate (#1F2937) but never set an explicit font color,
// so default black text on that dark fill was nearly unreadable. Body text
// now always gets an explicit color, and fills stay light throughout.
const HEADER_FILL = 'FF334155'
const HEADER_FONT = 'FFFFFFFF'
const PHASE_COLUMN_FILL = 'FFE8EEF9' // light blue tint -- marks phase-identity columns
const BAND_FILL = 'FFF3F4F6' // very light gray -- alternating sub-event bands
const BODY_FONT = 'FF1F2937'
const BORDER_COLOR = 'FFCBD5E1'

/** Builds and triggers a browser download of a SINGLE-SHEET .xlsx workbook
 * from the SAME row data TaskSwimlane already computed for display (phase
 * durations, pass/fail, and each row's own raw DTO -- see TaskSwimlane.tsx's
 * `Row.raw`) -- exporting from that shared source, rather than re-deriving
 * numbers from scratch, guarantees the file can never disagree with what's
 * on screen.
 *
 * Layout: task summary in the top-left corner, then one phase-grouped grid
 * below it -- each phase's identifying columns (route, timing, anomaly,
 * backward-leg) are MERGED vertically across every one of its own
 * lift/rotation/fork sub-event rows, so the sheet reads phase-first then
 * sub-event-by-sub-event underneath it, instead of repeating the same
 * phase info on every row. A phase with no sub-events gets exactly one row
 * (no merge needed). Merged cells aren't compatible with a native Excel
 * Table (ListObject) -- this trades that away deliberately for the
 * grouped, presentable layout that was asked for.
 *
 * `exceljs` is dynamically imported (not a top-level import) so its ~1MB
 * adds to the bundle only when someone actually clicks "Export to Excel",
 * not on every page load. */
export async function exportTaskTimingToExcel(params: {
  taskId: string
  taskType: string | null
  butlerIp: string
  phaseRows: Row[]
  subEventRows: Row[]
}): Promise<void> {
  const { taskId, taskType, butlerIp, phaseRows, subEventRows } = params
  const { default: ExcelJSModule } = await import('exceljs')
  const workbook = new ExcelJSModule.Workbook()
  workbook.creator = 'Butler Task Lifecycle Tracer'
  workbook.created = new Date()

  const sheet = workbook.addWorksheet('Task Timing')

  // -- Heading / subheading, top-left corner -------------------------------
  const headingRow = sheet.addRow(['Butler Task Lifecycle Tracer'])
  headingRow.font = { bold: true, size: 16 }
  const subheadingRow = sheet.addRow([taskTypeLabel(taskType)])
  subheadingRow.font = { bold: true, size: 12, color: { argb: 'FF64748B' } }
  sheet.addRow([])

  // -- Task summary, top-left corner -------------------------------------
  const failCount = subEventRows.filter((r) => r.passFail === 'fail' || r.sequenceViolation).length
  const titleRow = sheet.addRow(['Task Summary'])
  titleRow.font = { bold: true, size: 12 }
  const summaryPairs: [string, string | number][] = [
    ['Task ID', taskId],
    ['Task type', taskType ?? '-'],
    ['Butler IP', butlerIp],
    ['Phases', phaseRows.length],
    ['Sub-events', subEventRows.length],
    ['Failing sub-events', failCount],
  ]
  summaryPairs.forEach(([label, value]) => sheet.addRow([label, value]))
  sheet.addRow([])
  sheet.addRow([])

  // -- Phase-grouped grid --------------------------------------------------
  COLUMN_WIDTHS.forEach((w, i) => {
    sheet.getColumn(i + 1).width = w
  })

  const headerRow = sheet.addRow(HEADERS)
  headerRow.font = { bold: true, color: { argb: HEADER_FONT } }
  headerRow.eachCell((cell) => {
    cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: HEADER_FILL } }
  })
  const tableStartRow = headerRow.number

  const subEventsByPhase = new Map<number, Row[]>()
  subEventRows.forEach((r) => {
    const list = subEventsByPhase.get(r.phaseIndex) ?? []
    list.push(r)
    subEventsByPhase.set(r.phaseIndex, list)
  })

  phaseRows.forEach((p, i) => {
    const subs = subEventsByPhase.get(p.phaseIndex) ?? []
    const blockSize = Math.max(1, subs.length)
    const firstRowNum = sheet.lastRow!.number + 1
    const shaded = i % 2 === 1

    const phaseColumns = new Set([...FRONT_PHASE_COLUMNS, ...TAIL_PHASE_COLUMNS])

    for (let j = 0; j < blockSize; j++) {
      const sub: Row | undefined = subs[j]
      const row = sheet.addRow([
        j === 0 ? i + 1 : '',
        j === 0 ? `${p.fromAttr ?? '?'} -> ${p.attr ?? '?'}` : '',
        ...(sub ? subEventCells(sub) : blankSubEventCells()),
        j === 0 ? formatIso(p.startTimeIso) : '',
        j === 0 ? formatIso(p.endTimeIso) : '',
        j === 0 ? round2(p.duration) : '',
      ])
      row.eachCell({ includeEmpty: true }, (cell, colNumber) => {
        cell.font = { color: { argb: BODY_FONT } }
        if (phaseColumns.has(colNumber)) {
          cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: PHASE_COLUMN_FILL } }
        } else if (shaded) {
          cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: BAND_FILL } }
        }
      })
    }
    sheet.getCell(firstRowNum, 1).font = { bold: true, color: { argb: BODY_FONT } }
    sheet.getCell(firstRowNum, 2).font = { bold: true, color: { argb: BODY_FONT } }

    const lastRowNum = sheet.lastRow!.number
    if (blockSize > 1) {
      for (const col of [...FRONT_PHASE_COLUMNS, ...TAIL_PHASE_COLUMNS]) {
        sheet.mergeCells(firstRowNum, col, lastRowNum, col)
        sheet.getCell(firstRowNum, col).alignment = { vertical: 'top' }
      }
    }
  })

  if (phaseRows.length === 0) {
    sheet.addRow(['', 'No phases for this task.'])
  }

  const lastDataRow = sheet.lastRow!.number
  const thin = { style: 'thin' as const, color: { argb: BORDER_COLOR } }
  for (let r = tableStartRow; r <= lastDataRow; r++) {
    for (let c = 1; c <= HEADERS.length; c++) {
      sheet.getCell(r, c).border = { top: thin, left: thin, bottom: thin, right: thin }
    }
  }

  sheet.views = [{ state: 'frozen', ySplit: tableStartRow }]

  const buffer = await workbook.xlsx.writeBuffer()
  const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${taskId}-timing.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function blankSubEventCells(): (string | number)[] {
  return ['', '', '', '', '', '', '', '', '', '']
}

function subEventCells(r: Row): (string | number)[] {
  if (r.kind === 'lift') {
    const dto = r.raw as LiftEventDto | undefined
    return [
      'lift',
      dto?.context_label ?? 'simultaneousForkLift',
      formatIso(r.startTimeIso),
      formatIso(r.endTimeIso),
      round2(r.duration),
      '',
      r.overlapDuration > 0 ? round2(r.overlapDuration) : (dto?.understated_by_seconds ?? ''),
      '',
      dto?.target_height_mm ?? '',
      r.passFail ?? '',
    ]
  }
  if (r.kind === 'rotation') {
    const dto = r.raw as RotationEventDto | undefined
    return [
      'rotation',
      dto?.context_label ?? 'rotation',
      formatIso(r.startTimeIso),
      formatIso(r.endTimeIso),
      round2(r.duration),
      '',
      '',
      '',
      '',
      r.passFail ?? '',
    ]
  }
  if (r.kind === 'fork') {
    const dto = r.raw as ForkAdjustmentEventDto | undefined
    return [
      'fork',
      dto?.label ?? (dto?.direction === 'up' ? 'lift up' : 'lift down'),
      formatIso(r.startTimeIso),
      formatIso(r.endTimeIso),
      round2(r.duration),
      '',
      '',
      dto?.from_height_mm ?? '',
      dto?.to_height_mm ?? '',
      r.passFail ?? '',
    ]
  }
  return blankSubEventCells()
}

function taskTypeLabel(taskType: string | null): string {
  if (taskType === 'relay_pps_task') return 'Relay PPS Task'
  if (taskType === 'relay_group_task') return 'Relay Group Task'
  if (taskType === 'chargetask') return 'Charge Task'
  return taskType ?? 'Unknown Task Type'
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function formatIso(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString(undefined, { hour12: false })
}
