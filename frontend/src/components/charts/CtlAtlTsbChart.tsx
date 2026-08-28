import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { ChartTooltip } from "@/components/charts/ChartTooltip"
import type { CtlAtlTsbPoint } from "@/types/training"

/** CTL (fitness, line) + ATL (fatigue, line) + TSB (freshness, translucent
 * bar) on one chart -- same combination `dashboard/views/training.py` uses.
 */
export function CtlAtlTsbChart({ data, height = 280 }: { data: CtlAtlTsbPoint[]; height?: number }) {
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
        />
        <Tooltip content={<ChartTooltip formatter={(v) => Number(v).toFixed(1)} />} />
        <Bar dataKey="tsb" name="TSB (freshness)" fill="var(--band-amber)" fillOpacity={0.35} isAnimationActive={false} />
        <Line
          type="monotone"
          dataKey="ctl"
          name="CTL (fitness)"
          stroke="var(--band-blue)"
          strokeWidth={2.5}
          dot={false}
          isAnimationActive={false}
        />
        <Line
          type="monotone"
          dataKey="atl"
          name="ATL (fatigue)"
          stroke="var(--band-red)"
          strokeWidth={2.5}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
