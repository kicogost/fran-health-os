import { BAND_COLORS, BAND_COLORS_LIGHT, BAND_LABELS } from "@/lib/band"
import { useCountUp } from "@/hooks/useCountUp"
import type { ReadinessBand } from "@/types/today"

interface ReadinessRingProps {
  score: number | null
  band: ReadinessBand
  size?: number
}

/** The flagship central ring -- score 0-100, colored by readiness band.
 * Gradient stroke (light tint -> base color) and a soft blurred glow behind
 * it, the same "minimal glow" + gradient-arc treatment ui-ux-pro-max-skill's
 * actual "Dark Mode (OLED)" style data names, and the same visual language
 * Apple Watch activity rings / WHOOP's recovery ring use -- not a flat
 * single-color arc. The score counts up on mount rather than appearing
 * instantly (that dataset's "real-time number animations" effect).
 */
export function ReadinessRing({ score, band, size = 220 }: ReadinessRingProps) {
  const animated = useCountUp(score, 200)
  const strokeWidth = size * 0.075
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = animated !== null ? Math.max(0, Math.min(100, animated)) : 0
  const dashoffset = circumference * (1 - clamped / 100)
  const color = BAND_COLORS[band]
  const colorLight = BAND_COLORS_LIGHT[band]
  const gradientId = `readiness-gradient-${band}`

  return (
    <div className="relative" style={{ width: size, height: size }}>
      {score !== null && (
        <div
          className="absolute inset-[-20%] rounded-full blur-3xl opacity-25 pointer-events-none"
          style={{
            background: `radial-gradient(circle, ${color} 0%, transparent 70%)`,
          }}
          aria-hidden
        />
      )}
      <svg width={size} height={size} className="-rotate-90 relative">
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
        {score !== null && (
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
            style={{ filter: `drop-shadow(0 0 6px ${color}66)` }}
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
