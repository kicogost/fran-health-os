import { BedDouble, Bike, Dumbbell, Swords, TriangleAlert, type LucideIcon } from "lucide-react"
import { CARD_CLASS } from "@/lib/styles"
import type { Session, StructuralFlags } from "@/types/today"

// Plain-English versions of coach/rules.py's structural triggers (2026-08-30
// -- Francisco: "no fluff no acronyms," same fix already applied to Trends/
// Training; these mirror scripts/briefing.py's own CLI text verbatim so the
// app and the CLI briefing never say something different for the same
// trigger).
const WARNING_MESSAGES: Record<keyof StructuralFlags, string> = {
  downgrade_to_rest:
    "Your readiness has been low for several days in a row -- worth cutting back further today than the guidance above already suggests.",
  hrv_sustained_low:
    "Your HRV has been below your normal range for 3 days straight -- a sign your body could use more recovery.",
  tsb_persistently_negative:
    "You've been carrying fatigue for over 4 days without a real freshness rebound.",
  monotony_strain:
    "This week's training has been both hard and repetitive -- a combination linked to higher burnout/injury risk. Worth an easier day.",
}

const SESSION_ICONS: Record<string, LucideIcon> = {
  bjj: Swords,
  bike: Bike,
  calisthenics: Dumbbell,
  rest: BedDouble,
}

interface SessionCardProps {
  weekdayName: string
  sessions: Session[]
  structuralFlags: StructuralFlags
}

/** Today's guidance -- real coach/rules.py + coach/briefing.py output
 * (Phase 7), the same computation scripts/briefing.py prints from the CLI.
 * Mirrors dashboard/views/today.py's "Today's guidance" card.
 */
export function SessionCard({ weekdayName, sessions, structuralFlags }: SessionCardProps) {
  const warnings = (Object.keys(WARNING_MESSAGES) as (keyof StructuralFlags)[]).filter(
    (key) => structuralFlags[key],
  )

  return (
    <div className={`${CARD_CLASS} p-5`}>
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
        Today&apos;s guidance -- {weekdayName.charAt(0).toUpperCase() + weekdayName.slice(1)}
      </p>
      {sessions.length === 0 ? (
        <p className="text-lg font-medium text-foreground">
          Nothing scheduled today per <code className="text-sm">comp_prep.weekly_template</code>.
        </p>
      ) : (
        <div className="space-y-4">
          {sessions.map((session, i) => {
            const Icon = SESSION_ICONS[session.type] ?? Dumbbell
            return (
              <div key={i} className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent">
                  <Icon className="h-4 w-4 text-foreground" strokeWidth={2} />
                </span>
                <div>
                  <p className="text-lg font-medium text-foreground leading-snug">
                    {session.label}
                  </p>
                  <p className="text-sm text-[var(--band-blue)] mt-0.5 font-medium">
                    {session.instruction}
                  </p>
                  {(session.format || session.distance_km_range || session.duration_min) && (
                    <p className="text-sm text-muted-foreground mt-1">
                      {session.format}
                      {session.distance_km_range &&
                        `${session.distance_km_range[0]}-${session.distance_km_range[1]}km`}
                      {session.zone_range && ` (${session.zone_range})`}
                      {session.duration_min && `${session.duration_min} min`}
                    </p>
                  )}
                  {session.notes && (
                    <p className="text-sm text-muted-foreground/80 mt-0.5 italic">
                      {session.notes}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {warnings.map((key) => (
            <div
              key={key}
              className="flex items-start gap-2 rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2 text-sm text-foreground"
            >
              <span className="relative flex h-4 w-4 shrink-0 mt-0.5" aria-hidden>
                <span className="absolute inline-flex h-full w-full rounded-full bg-[var(--band-amber)]/50 animate-ping motion-reduce:hidden" />
                <TriangleAlert
                  className="relative h-4 w-4 text-[var(--band-amber)]"
                  strokeWidth={2.25}
                />
              </span>
              <span>{WARNING_MESSAGES[key]}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
