interface TooltipPayloadEntry {
  name?: string
  value?: number | string
  color?: string
}

interface ChartTooltipProps {
  active?: boolean
  label?: string
  payload?: TooltipPayloadEntry[]
  unit?: string
  formatter?: (value: number | string) => string
}

/** Dark-themed tooltip content -- recharts' default tooltip assumes a light
 * background, so every chart on this app passes this in via `content=`.
 */
export function ChartTooltip({ active, label, payload, unit, formatter }: ChartTooltipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 shadow-lg text-xs">
      <p className="text-muted-foreground mb-1">{label}</p>
      {payload.map((entry, i) => (
        <p key={i} className="text-foreground font-medium" style={{ color: entry.color }}>
          {entry.name}: {formatter && entry.value !== undefined ? formatter(entry.value) : entry.value}
          {unit ? ` ${unit}` : ""}
        </p>
      ))}
    </div>
  )
}
