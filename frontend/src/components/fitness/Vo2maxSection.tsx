import { useEffect, useState } from "react"
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Wind } from "lucide-react"
import { fetchVo2max } from "@/lib/api"
import { CARD_CLASS } from "@/lib/styles"
import type { Vo2maxPayload } from "@/types/fitness"

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function toTs(date: string): number {
  return new Date(`${date}T00:00:00`).getTime()
}

function formatDate(ts: number): string {
  const d = new Date(ts)
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`
}

interface ChartRow {
  ts: number
  measured?: number
  estimate?: number
  band?: [number, number]
}

/** VO2max: the last real Garmin measurement leads; the RHR-calibrated
 * estimate since then is secondary and always shown with its range
 * (metrics/vo2max.py, researched 2026-10-06). BJJ heart-rate recovery is
 * context below the number, never part of it. Independent of the Trends
 * window selector -- it shows the full history of real measurements.
 */
export function Vo2maxSection() {
  const [data, setData] = useState<Vo2maxPayload | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchVo2max()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (failed) return null
  if (!data) return null

  const latest = data.latest_measurement
  const current = data.current
  const hasEstimate = current.status === "estimate" || current.status === "low_confidence"

  const rows: ChartRow[] = [
    ...data.measurements.map((m) => ({ ts: toTs(m.date), measured: m.value })),
    ...data.estimate_series.map((p) => ({
      ts: toTs(p.date),
      estimate: p.value,
      band: [p.low, p.high] as [number, number],
    })),
  ].sort((a, b) => a.ts - b.ts)

  const [refLow, refHigh] = data.context.bjj_reference_range

  return (
    <div className={`${CARD_CLASS} p-5`}>
      <div className="flex items-center gap-2 mb-3">
        <Wind className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Aerobic fitness · VO2max
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-x-8 gap-y-3 mb-3">
        <div>
          <p className="text-4xl font-semibold tabular-nums tracking-tight text-foreground">
            {latest ? latest.value.toFixed(0) : "—"}
            <span className="text-sm font-normal text-muted-foreground ml-1">ml/kg/min</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {latest
              ? `Last measured ${formatDate(toTs(latest.date))} · ${latest.days_ago} days ago`
              : "No real measurement yet"}
          </p>
        </div>
        {hasEstimate && current.value !== null && (
          <div>
            <p className="text-2xl font-semibold tabular-nums tracking-tight text-[var(--band-blue)]">
              ~{current.value.toFixed(0)}
              <span className="text-sm font-normal text-muted-foreground ml-1">
                ({current.low?.toFixed(0)}–{current.high?.toFixed(0)})
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              Estimated now{current.status === "low_confidence" ? " · low confidence" : ""}
            </p>
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground leading-snug mb-4">{data.meaning.headline}</p>

      {rows.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <ReferenceArea
              y1={refLow}
              y2={refHigh}
              fill="var(--muted-foreground)"
              fillOpacity={0.07}
              ifOverflow="extendDomain"
            />
            <XAxis
              dataKey="ts"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={formatDate}
              stroke="var(--muted-foreground)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              minTickGap={40}
            />
            <YAxis
              stroke="var(--muted-foreground)"
              fontSize={11}
              tickLine={false}
              axisLine={false}
              width={40}
              domain={[40, "auto"]}
            />
            <Tooltip content={<Vo2Tooltip />} />
            <Area
              dataKey="band"
              stroke="none"
              fill="var(--band-blue)"
              fillOpacity={0.12}
              connectNulls
              isAnimationActive={false}
            />
            <Line
              dataKey="estimate"
              stroke="var(--band-blue)"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
            <Scatter dataKey="measured" fill="var(--band-green)" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      <p className="text-[11px] text-muted-foreground/70 mt-1">
        Green dots: real Garmin measurements (from runs). Blue dashed line and band: estimate
        and likely range. Grey band: VO2max range reported for BJJ athletes ({refLow}–{refHigh}).
      </p>

      <div className="grid gap-3 sm:grid-cols-3 mt-4">
        <ContextStat
          label="Resting heart rate (28-day)"
          then={data.context.rhr_28d_at_anchor}
          now={data.context.rhr_28d_now}
          unit="bpm"
        />
        <ContextStat
          label="Overnight HRV (28-day)"
          then={data.context.hrv_28d_at_anchor}
          now={data.context.hrv_28d_now}
          unit="ms"
        />
        <div className="rounded-lg bg-accent/40 p-3">
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">
            BJJ: heart-rate drop in rests
          </p>
          {data.bjj_recovery.length ? (
            data.bjj_recovery.slice(-4).map((s) => (
              <p key={s.date} className="text-xs text-foreground tabular-nums">
                {formatDate(toTs(s.date))}: −{s.avg_drop_bpm.toFixed(0)} bpm
              </p>
            ))
          ) : (
            <p className="text-xs text-muted-foreground">No auto-detected rounds yet.</p>
          )}
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground/70 leading-snug mt-3">
        How this is estimated: Garmin can't measure VO2max without runs or a power meter. The
        estimate takes your own real measurements
        {data.calibration ? ` (${data.calibration.n_anchors} usable)` : ""}, fits a personal
        version of the resting-heart-rate method (max heart rate {data.hr_max} ÷ 28-day resting
        heart rate), and widens the range the longer it's been since a real measurement. BJJ
        heart rate, HRV and weight are shown as context only — none of them can be turned into a
        VO2max number without knowing the workload.
        {data.weight_only &&
          ` Weight alone moves it: at today's weight your last measurement works out to ${data.weight_only.value.toFixed(1)}.`}
      </p>
    </div>
  )
}

function ContextStat({
  label,
  then,
  now,
  unit,
}: {
  label: string
  then?: number | null
  now: number | null
  unit: string
}) {
  return (
    <div className="rounded-lg bg-accent/40 p-3">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1">{label}</p>
      <p className="text-sm text-foreground tabular-nums">
        {then != null ? `${then.toFixed(0)} ${unit}` : "—"} → {now != null ? `${now.toFixed(0)} ${unit}` : "—"}
      </p>
      <p className="text-[11px] text-muted-foreground">at last measurement → now</p>
    </div>
  )
}

interface Vo2TooltipProps {
  active?: boolean
  payload?: { payload: ChartRow }[]
}

function Vo2Tooltip({ active, payload }: Vo2TooltipProps) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 shadow-lg text-xs">
      <p className="text-muted-foreground mb-1">{formatDate(row.ts)}</p>
      {row.measured !== undefined && (
        <p className="font-medium" style={{ color: "var(--band-green)" }}>
          Measured: {row.measured.toFixed(0)}
        </p>
      )}
      {row.estimate !== undefined && row.band && (
        <p className="font-medium" style={{ color: "var(--band-blue)" }}>
          Estimate: {row.estimate.toFixed(1)} ({row.band[0].toFixed(0)}–{row.band[1].toFixed(0)})
        </p>
      )}
    </div>
  )
}
