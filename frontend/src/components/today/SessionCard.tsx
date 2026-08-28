import type { Session, StructuralFlags } from "@/types/today"

const WARNING_MESSAGES: Record<keyof StructuralFlags, string> = {
  downgrade_to_rest:
    "2+ consecutive red days or 3 amber days in a row -- consider downgrading further.",
  hrv_sustained_low: "HRV has sat >1 SD below baseline for 3 straight days.",
  tsb_persistently_negative: "TSB has been negative for 4+ straight days.",
  monotony_strain: "High monotony this week with strain in the recent top quartile.",
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
    <div className="rounded-xl border border-border bg-card p-6">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
        Today&apos;s guidance -- {weekdayName.charAt(0).toUpperCase() + weekdayName.slice(1)}
      </p>
      {sessions.length === 0 ? (
        <p className="text-lg font-medium text-foreground">
          Nothing scheduled today per <code className="text-sm">comp_prep.weekly_template</code>.
        </p>
      ) : (
        <div className="space-y-3">
          {sessions.map((session, i) => (
            <div key={i}>
              <p className="text-lg font-medium text-foreground">
                {session.label} -- {session.instruction}
              </p>
              {(session.format ?? session.notes) && (
                <p className="text-sm text-muted-foreground mt-0.5">
                  {session.format ?? session.notes}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mt-4 space-y-2">
          {warnings.map((key) => (
            <div
              key={key}
              className="flex items-start gap-2 rounded-lg border border-[var(--band-amber)]/30 bg-[var(--band-amber)]/10 px-3 py-2 text-sm text-foreground"
            >
              <span aria-hidden>⚠</span>
              <span>
                <span className="font-medium">Structural:</span> {WARNING_MESSAGES[key]}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
