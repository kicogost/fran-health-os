import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { ChartTooltip } from "@/components/charts/ChartTooltip"

interface StackedBarChartProps {
  data: Record<string, unknown>[]
  bars: { key: string; label: string; color: string }[]
  height?: number
  // Off by default (sleep stages' original 4 fixed keys don't need one --
  // the card title + colors already say enough). Added 2026-08-30 for the
  // Training page's sport breakdown, where the set of colored series
  // varies by account/time and isn't otherwise labeled anywhere on screen.
  showLegend?: boolean
}

/** Generic stacked bar chart -- sleep stages (deep/light/rem/awake) and load
 * by sport both share this exact shape, just with different keys/colors.
 */
export function StackedBarChart({ data, bars, height = 240, showLegend = false }: StackedBarChartProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
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
        />
        <Tooltip content={<ChartTooltip />} />
        {showLegend && (
          <Legend
            wrapperStyle={{ fontSize: 11, color: "var(--muted-foreground)" }}
            iconSize={8}
            iconType="circle"
          />
        )}
        {bars.map(({ key, label, color }) => (
          <Bar key={key} dataKey={key} name={label} stackId="stack" fill={color} isAnimationActive={false} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
