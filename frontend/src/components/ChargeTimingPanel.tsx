import type { ChargeTimingDto, RotationEventDto } from '../lib/api'

/** Charge-cycle timing breakdown for chargetask -- see
 * api/routes.py's charge_timing attachment and parsers/charge_timing.py's
 * module docstring for the real-trace-derived milestone sequence this
 * renders: assigned -> charger_reinit -> charger -> charging_started ->
 * charging_complete -> return dispatched -> charger_reinit (backing out)
 * -> parked (ordinary relay waypoints, not a dedicated parking zone). */
export function ChargeTimingPanel({
  timing,
  rotationEvents,
}: {
  timing: ChargeTimingDto
  rotationEvents: RotationEventDto[]
}) {
  const outboundRotations = timing.charging_started_at
    ? rotationEvents.filter((r) => r.timestamp < timing.charging_started_at!)
    : []
  const returnRotations = timing.return_dispatched_at
    ? rotationEvents.filter((r) => r.timestamp >= timing.return_dispatched_at!)
    : []

  const fmt = (s: number | null) => (s != null ? `${s.toFixed(1)}s` : '-')
  const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour12: false }) : '-')
  const leg = (s: number | null) => (s != null ? ` (+${s.toFixed(1)}s)` : '')
  const fmtPct = (pct: number | null) => (pct != null ? `${pct.toFixed(0)}%` : '-')

  const dockedToChargingLabel =
    timing.docked_to_charging_started_seconds != null
      ? timing.docked_to_charging_started_seconds < 1
        ? 'near-instant (<1s) -- no separate wait to start charging'
        : `${timing.docked_to_charging_started_seconds.toFixed(1)}s wait before charging began`
      : '-'

  return (
    <div className="border border-gray-700 bg-gray-800/60 rounded-lg p-4 space-y-4">
      <h2 className="text-sm font-semibold text-gray-200">Charge cycle breakdown</h2>

      {/* Charging time vs. the return-to-reinit time are deliberately two
          separate, equally-prominent stats here -- not lumped into one
          "return travel" number -- so the split the user asked to see is
          obvious at a glance rather than buried in the detail rows below. */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <Stat label="Outbound travel" value={fmt(timing.outbound_travel_seconds)} />
        <Stat label="Charging duration" value={fmt(timing.charging_duration_seconds)} highlight />
        <Stat label="Charging stop -> back at reinit" value={fmt(timing.charging_stop_to_reinit_seconds)} highlight />
        <Stat label="Total cycle time" value={fmt(timing.total_seconds)} highlight />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
        <Stat label="Battery at charger arrival" value={fmtPct(timing.battery_pct_at_charger_arrival)} />
        <Stat label="Battery at charging complete" value={fmtPct(timing.battery_pct_at_charging_complete)} />
        <Stat label="Return travel (stop to parked)" value={fmt(timing.return_travel_seconds)} />
      </div>

      {/* Whether charging ended because the bot reached full charge, or
          because something (an operator/API) cut it short -- the graceful
          stop ack's `graceful_stop_reason` is the only place in the log
          that distinguishes the two, and it lands only seconds before
          `charging_complete` fires, i.e. it's what actually triggered the
          end of the charge task, not an unrelated coincident event. */}
      {timing.charging_stopped_via_api && (
        <div className="border border-amber-700/60 bg-amber-900/20 rounded-md p-2.5 text-sm flex items-center justify-between gap-2">
          <span className="text-amber-300 font-medium">⚠ Charging ended via API stop, not a full charge</span>
          <span className="font-mono text-amber-200 text-xs">
            reason: {timing.graceful_stop_reason} @ {fmtTime(timing.graceful_stop_at)}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs text-gray-400">
        <div className="space-y-1">
          <p className="text-gray-300 font-medium">Outbound (assigned to docked)</p>
          <Row label="Assigned" value={fmtTime(timing.assigned_at)} />
          <Row
            label="Reached charger_reinit"
            value={`${fmtTime(timing.reached_charger_reinit_at)}${leg(timing.assigned_to_reinit_seconds)}`}
          />
          <Row
            label="Reached charger (docked)"
            value={`${fmtTime(timing.reached_charger_at)}${leg(timing.reinit_to_charger_seconds)}`}
          />
          {/* Answers directly: is it just reinit-barcode -> charger-barcode,
              or does charging actually wait after docking before it starts?
              See ChargeTiming.docked_to_charging_started_seconds. */}
          <Row label="Charging started" value={`${fmtTime(timing.charging_started_at)} -- ${dockedToChargingLabel}`} />
          <Row label="Rotations en route" value={String(outboundRotations.length)} />
        </div>
        <div className="space-y-1">
          <p className="text-gray-300 font-medium">Return (charged to parked)</p>
          <Row
            label="Charging complete"
            value={
              timing.charging_stopped_via_api
                ? `${fmtTime(timing.charging_complete_at)} -- stopped via API (${timing.graceful_stop_reason})`
                : fmtTime(timing.charging_complete_at)
            }
          />
          <Row label="Return dispatched" value={fmtTime(timing.return_dispatched_at)} />
          <Row
            label="Backed out to charger_reinit"
            value={`${fmtTime(timing.return_reached_charger_reinit_at)}${leg(timing.charging_stop_to_reinit_seconds)}`}
          />
          <Row
            label="Parked (relay waypoint)"
            value={`${fmtTime(timing.parked_at)}${leg(timing.reinit_to_parked_seconds)}`}
          />
          <Row label="Rotations en route" value={String(returnRotations.length)} />
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="border border-gray-700 bg-gray-800/60 rounded-md p-2.5">
      <div className="text-gray-400 text-xs">{label}</div>
      <div className={highlight ? 'text-blue-300 font-semibold' : 'text-gray-100'}>{value}</div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span>{label}</span>
      <span className="font-mono text-gray-300">{value}</span>
    </div>
  )
}
