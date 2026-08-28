import { BAND_COLORS, BAND_LABELS } from "@/lib/band"
import type { ReadinessBand } from "@/types/today"

interface ReadinessRingProps {
  score: number | null
  band: ReadinessBand
  size?: number
}

/** The flagship central ring -- score 0-100, colored by readiness band.
 * Same circumference/dashoffset technique as the Streamlit dashboard's
 * `theme.py: ring_svg()` (rounded stroke caps, track + progress arc), now
 * a real React component instead of an injected raw-SVG string.
 */
export function ReadinessRing({ score, band, size = 220 }: ReadinessRingProps) {
  const strokeWidth = size * 0.075
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = score !== null ? Math.max(0, Math.min(100, score)) : 0
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
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
        <span className="text-5xl font-semibold tabular-nums text-foreground">
          {score !== null ? Math.round(score) : "–"}
        </span>
        <span
          className="text-xs font-medium uppercase tracking-wider"
          style={{ color }}
        >
          {BAND_LABELS[band]}
        </span>
      </div>
    </div>
  )
}
