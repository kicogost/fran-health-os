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

  for (const p of weightRaw ?? []) set(p.date, "raw", p.value)
  for (const p of weightEwma ?? []) set(p.date, "ewma", p.value)
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
