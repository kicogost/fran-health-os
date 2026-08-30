import { useCountUp } from "@/hooks/useCountUp"

const ZONE_LABELS: Record<string, string> = {
  light: "Light",
  moderate: "Moderate",
  high: "High",
  all_out: "All Out",
}

interface StrainRingProps {
  strain: number | null
  zone: string | null
  size?: number
}

/** Strain's peer ring to ReadinessRing -- same gradient-stroke + glow
 * treatment, but deliberately always blue-toned rather than colored by
 * band. Strain isn't "good" or "bad" the way readiness is (a 17 before a
 * planned hard day is fine, the same 17 before a rest day isn't) --
 * WHOOP's own real app uses a fixed blue/cyan hue for Strain regardless of
 * magnitude, unlike Recovery's green/yellow/red, and this follows the same
 * convention rather than inventing a strain-specific traffic-light scheme
 * that would misleadingly imply "high strain = bad."
 *
 * 0-21 scale (WHOOP's own published range) instead of readiness' 0-100.
 */
export function StrainRing({ strain, zone, size = 220 }: StrainRingProps) {
  const animated = useCountUp(strain, 200)
  const strokeWidth = size * 0.075
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = animated !== null ? Math.max(0, Math.min(21, animated)) : 0
  const dashoffset = circumference * (1 - clamped / 21)
  const color = "var(--band-blue)"
  const colorLight = "var(--band-blue-light)"

  return (
    <div className="relative" style={{ width: size, height: size }}>
      {strain !== null && (
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
          <linearGradient id="strain-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
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
        {strain !== null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            stroke="url(#strain-gradient)"
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
        <span className="text-5xl font-semibold tabular-nums tracking-tight text-foreground">
          {animated !== null ? animated.toFixed(1) : "–"}
        </span>
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {zone ? (ZONE_LABELS[zone] ?? zone) : "No data yet"}
        </span>
      </div>
    </div>
  )
}
