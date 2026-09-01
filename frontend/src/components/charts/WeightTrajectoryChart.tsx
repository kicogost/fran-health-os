import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartTooltip } from "@/components/charts/ChartTooltip"
import type { CompPrepPayload } from "@/types/compPrep"

interface WeightTrajectoryChartProps {
  weightRaw: CompPrepPayload["weight_raw"]
  weightEwma: CompPrepPayload["weight_ewma"]
  requiredPath: CompPrepPayload["required_path"]
  projection: CompPrepPayload["projection"]
  weightLimitKg: number
  height?: number
}

// The backend (api/comp_prep.py) sends the FULL weight history -- real
// weigh-ins go back to 2021-06-17 per CLAUDE.md, sparse until 2026 -- in the
// same series as the ~8-week required-path/projection lines. The chart's
// x-axis is a category axis (one equal-width slot per unique date
// regardless of the real time gap between them), so multiple years of
// mostly-empty history squeezed the actual decision-relevant comp-countdown
// window into a sliver of the chart and made the date labels overlap.
// Trimming the RAW/EWMA history to a trailing window before it ever reaches
// Recharts is the smaller, lower-risk fix (vs. switching the axis to a real
// numeric/time scale) -- same pattern Trends already uses with its
// 30/90/365-day selector, just fixed here rather than user-selectable since
// this page has exactly one relevant window (the comp countdown).
const TRAILING_RAW_DAYS = 150

function shiftIsoDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Weight trajectory vs. the required path to the division limit, with a
 * shaded 95% CI band around the current-trend projection when there's
 * enough data for one (design principle 6: never show a CI from too few
 * points). Mirrors dashboard/views/comp_prep.py's chart exactly.
 */
export function WeightTrajectoryChart({
  weightRaw,
  weightEwma,
  requiredPath,
  projection,
  weightLimitKg,
  height = 320,
}: WeightTrajectoryChartProps) {
  const merged = new Map<string, Record<string, unknown>>()
  const set = (date: string, key: string, value: unknown) => {
    const entry = merged.get(date) ?? { date }
    entry[key] = value
    merged.set(date, entry)
  }

  // Anchor mirrors comp_prep.py's own `today` (the last real weigh-in
  // date, which is also required_path[0]) -- the required-path/projection
  // series are never filtered, they're already just the short future comp
  // window.
  const anchorDate = requiredPath?.[0]?.date ?? weightEwma?.at(-1)?.date ?? weightRaw?.at(-1)?.date
  const cutoffDate = anchorDate ? shiftIsoDate(anchorDate, -TRAILING_RAW_DAYS) : null
  const inWindow = (d: string) => cutoffDate === null || d >= cutoffDate

  for (const p of weightRaw ?? []) if (inWindow(p.date)) set(p.date, "raw", p.value)
  for (const p of weightEwma ?? []) if (inWindow(p.date)) set(p.date, "ewma", p.value)
  for (const p of requiredPath ?? []) set(p.date, "required", p.value)
  if (projection) {
    for (const p of projection.mid) set(p.date, "projected", p.value)
    for (let i = 0; i < projection.ci_low.length; i++) {
      set(projection.ci_low[i].date, "ciRange", [
        projection.ci_low[i].value,
        projection.ci_high[i].value,
      ])
    }
  }

  const data = Array.from(merged.values()).sort((a, b) =>
    String(a.date).localeCompare(String(b.date)),
  )

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
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
          domain={["auto", "auto"]}
        />
        <Tooltip content={<ChartTooltip formatter={(v) => Number(v).toFixed(2)} />} />
        {projection && (
          <Area
            dataKey="ciRange"
            name="projection 95% CI"
            stroke="none"
            fill="var(--band-amber)"
            fillOpacity={0.15}
            isAnimationActive={false}
          />
        )}
        <Scatter dataKey="raw" name="raw weigh-ins" fill="var(--band-blue)" fillOpacity={0.3} isAnimationActive={false} />
        <Line
          type="monotone"
          dataKey="ewma"
          name="EWMA"
          stroke="var(--band-blue)"
          strokeWidth={2.5}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="required"
          name="required path"
          stroke="var(--band-green)"
          strokeWidth={2}
          strokeDasharray="6 4"
          dot={false}
          isAnimationActive={false}
        />
        {projection && (
          <Line
            type="monotone"
            dataKey="projected"
            name="projected (current trend)"
            stroke="var(--band-amber)"
            strokeWidth={2}
            strokeDasharray="2 3"
            dot={false}
            isAnimationActive={false}
          />
        )}
        <ReferenceLine
          y={weightLimitKg}
          stroke="var(--band-red)"
          strokeDasharray="2 2"
          label={{ value: "division limit", fill: "var(--band-red)", fontSize: 11, position: "insideTopRight" }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
