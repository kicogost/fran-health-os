import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartTooltip } from "@/components/charts/ChartTooltip"

interface TrendChartProps {
  raw: { date: string; value: number }[]
  smoothed: { date: string; value: number }[]
  color: string
  unit?: string
  height?: number
}

/** Raw points (faint dots) behind a smoothed line -- the same "raw always
 * visible behind smoothed" convention the Streamlit dashboard's theme.py
 * established (`add_raw_and_smoothed()`), carried over rather than dropped
 * in the rewrite.
 */
export function TrendChart({ raw, smoothed, color, unit, height = 220 }: TrendChartProps) {
  // raw and smoothed always share the same dates in the same order --
  // smoothed is derived directly from the raw observations one-for-one
  // (api/trends.py: _smooth()), so a plain index zip is safe here.
  const merged = smoothed.map((s, i) => ({
    date: s.date,
    smoothed: s.value,
    raw: raw[i]?.value,
  }))

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={merged} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
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
        <Tooltip
          content={<ChartTooltip unit={unit} formatter={(v) => Number(v).toFixed(1)} />}
        />
        <Scatter dataKey="raw" name="raw" fill={color} fillOpacity={0.35} isAnimationActive={false} />
        <Line
          type="monotone"
          dataKey="smoothed"
          name="smoothed"
          stroke={color}
          strokeWidth={2.5}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
