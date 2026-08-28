import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"

/** A labeled slider with its current value shown -- shared across the BJJ
 * (session RPE) and Wellness (the 4 Hooper-Mackinnon sub-scores) tabs.
 */
export function SliderField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <Label>{label}</Label>
        <span className="text-sm text-muted-foreground tabular-nums">{value}</span>
      </div>
      <Slider value={[value]} onValueChange={(v) => onChange(v[0])} min={min} max={max} step={1} />
    </div>
  )
}
