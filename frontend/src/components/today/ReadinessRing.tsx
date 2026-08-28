import { BAND_COLORS, BAND_LABELS } from "@/lib/band"
import { useCountUp } from "@/hooks/useCountUp"
import type { ReadinessBand } from "@/types/today"

interface ReadinessRingProps {
  score: number | null
  band: ReadinessBand
  size?: number
}

/** The flagship central ring -- score 0-100, colored by readiness band.
 * Same circumference/dashoffset technique as the Streamlit dashboard's
 * `theme.py: ring_svg()` (rounded stroke caps, track + progress arc), now
 * a real React component instead of an injected raw-SVG string. The score
 * counts up on mount rather than appearing instantly -- a "real-time
 * number animation," the exact effect ui-reasoning.csv names for this kind
 * of status dashboard (see lib/styles.ts's comment for the source).
 */
export function ReadinessRing({ score, band, size = 220 }: ReadinessRingProps) {
  const animated = useCountUp(score, 200)
  const strokeWidth = size * 0.075
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = animated !== null ? Math.max(0, Math.min(100, animated)) : 0
  const dashoffset = circumference * (1 - clamped / 100)
  const color = BAND_COLORS[band]

  return (
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
        {score !== null && (
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
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
        <span className="text-5xl font-semibold tabular-nums text-foreground">
          {animated !== null ? Math.round(animated) : "–"}
        </span>
        <span className="text-xs font-medium uppercase tracking-wider" style={{ color }}>
          {BAND_LABELS[band]}
        </span>
      </div>
    </div>
  )
}
