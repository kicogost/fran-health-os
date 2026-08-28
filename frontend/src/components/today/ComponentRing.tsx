import { BAND_COLORS, scoreToBand } from "@/lib/band"

const COMPONENT_LABELS: Record<string, string> = {
  hrv: "HRV",
  sleep: "Sleep",
  rhr: "RHR",
  tsb: "Freshness",
  subjective: "Wellness",
}

interface ComponentRingProps {
  componentKey: string
  score: number
  size?: number
}

/** A small ring for one readiness sub-component (HRV/RHR/sleep/TSB/
 * subjective), colored by the SAME 75/55 band thresholds as the main ring
 * (lib/band.ts) so a component ring and the overall ring never disagree on
 * what "amber" looks like.
 */
export function ComponentRing({ componentKey, score, size = 64 }: ComponentRingProps) {
  const strokeWidth = size * 0.12
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, score))
  const dashoffset = circumference * (1 - clamped / 100)
  const color = BAND_COLORS[scoreToBand(score)]

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="var(--border)"
            strokeWidth={strokeWidth}
            fill="none"
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke={color}
            strokeWidth={strokeWidth}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashoffset}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-semibold tabular-nums">{Math.round(score)}</span>
        </div>
      </div>
      <span className="text-[0.7rem] text-muted-foreground">
        {COMPONENT_LABELS[componentKey] ?? componentKey}
      </span>
    </div>
  )
}
