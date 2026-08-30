import { BAND_COLORS, BAND_COLORS_LIGHT, scoreToBand } from "@/lib/band"
import { useCountUp } from "@/hooks/useCountUp"

const COMPONENT_LABELS: Record<string, string> = {
  hrv: "HRV",
  sleep: "Sleep",
  rhr: "RHR",
  subjective: "Wellness",
}

interface ComponentRingProps {
  componentKey: string
  score: number
  displayRaw?: string | null
  excluded?: boolean
  size?: number
}

/** A small ring for one readiness sub-component (HRV/RHR/sleep/subjective --
 * TSB was removed from the composite entirely, ADR 0007, so it never
 * appears here anymore), colored by the SAME 75/55 band thresholds as the
 * main ring (lib/band.ts) so a component ring and the overall ring never
 * disagree on what "amber" looks like. Same gradient-stroke treatment as
 * the main ring, scaled down. Counts up on mount, same as ReadinessRing.
 *
 * The number inside the ring is always the 0-100 readiness SCORE, never the
 * raw sensor reading -- real mix-up found 2026-08-30, "HRV 47" was
 * reasonably read as 47ms when it was really a deviation-based score with
 * real HRV at 90ms. `displayRaw` (e.g. "90ms") renders below the label so
 * the actual reading is always visible, not just the abstracted score.
 *
 * `excluded` (weight_used === 0, a general mechanism -- originally
 * motivated by TSB while its load-data coverage was known unreliable, kept
 * for any future zero-weighted component) renders the ring desaturated
 * with a dashed track and "not counted" in place of the label, so a
 * component contributing zero weight never looks like a real, scored 0.
 */
export function ComponentRing({
  componentKey,
  score,
  displayRaw,
  excluded = false,
  size = 64,
}: ComponentRingProps) {
  const animated = useCountUp(score, 180) ?? 0
  const strokeWidth = size * 0.12
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(100, animated))
  const dashoffset = circumference * (1 - clamped / 100)
  const band = scoreToBand(score)
  const color = excluded ? "var(--muted-foreground)" : BAND_COLORS[band]
  const colorLight = excluded ? "var(--muted-foreground)" : BAND_COLORS_LIGHT[band]
  const gradientId = `component-gradient-${componentKey}`

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative" style={{ width: size, height: size, opacity: excluded ? 0.4 : 1 }}>
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
            strokeDasharray={excluded ? "3 4" : undefined}
          />
          {!excluded && (
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
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-semibold tabular-nums">
            {excluded ? "–" : Math.round(animated)}
          </span>
        </div>
      </div>
      <span className="text-[0.7rem] text-muted-foreground">
        {COMPONENT_LABELS[componentKey] ?? componentKey}
      </span>
      <span className="text-[0.65rem] text-muted-foreground/70 -mt-1">
        {excluded ? "not counted" : (displayRaw ?? " ")}
      </span>
    </div>
  )
}
