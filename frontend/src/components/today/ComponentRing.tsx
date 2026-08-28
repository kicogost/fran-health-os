import { BAND_COLORS, BAND_COLORS_LIGHT, scoreToBand } from "@/lib/band"
import { useCountUp } from "@/hooks/useCountUp"

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
 * what "amber" looks like. Same gradient-stroke treatment as the main ring,
 * scaled down. Counts up on mount, same as ReadinessRing.
 */
export function ComponentRing({ componentKey, score, size = 64 }: ComponentRingProps) {
  const animated = useCountUp(score, 180) ?? 0
  const strokeWidth = size * 0.12
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, animated))
  const dashoffset = circumference * (1 - clamped / 100)
  const band = scoreToBand(score)
  const color = BAND_COLORS[band]
  const colorLight = BAND_COLORS_LIGHT[band]
  const gradientId = `component-gradient-${componentKey}`

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <defs>
            <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={colorLight} />
              <stop offset="100%" stopColor={color} />
            </linearGradient>
          </defs>
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
            stroke={`url(#${gradientId})`}
            strokeWidth={strokeWidth}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashoffset}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-semibold tabular-nums">{Math.round(animated)}</span>
        </div>
      </div>
      <span className="text-[0.7rem] text-muted-foreground">
        {COMPONENT_LABELS[componentKey] ?? componentKey}
      </span>
    </div>
  )
}
