import { useEffect, useState } from "react"
import { Utensils } from "lucide-react"
import { ApiError, fetchToday } from "@/lib/api"
import { BAND_COLORS } from "@/lib/band"
import { CARD_CLASS } from "@/lib/styles"
import type { TodayPayload } from "@/types/today"
import { ReadinessRing } from "@/components/today/ReadinessRing"
import { StrainRing } from "@/components/today/StrainRing"
import { ComponentRing } from "@/components/today/ComponentRing"
import { SessionCard } from "@/components/today/SessionCard"

function formatHeaderDate(isoDate: string, weekdayName: string): string {
  const [, month, day] = isoDate.split("-").map(Number)
  const monthName = new Date(2000, month - 1, 1).toLocaleString("en-US", { month: "short" })
  const weekday = weekdayName.charAt(0).toUpperCase() + weekdayName.slice(1)
  return `${weekday}, ${monthName} ${day}`
}

export function TodayPage() {
  const [data, setData] = useState<TodayPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchToday()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : "Could not reach the API.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return <div className="p-8 text-muted-foreground">Loading...</div>
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="max-w-lg mx-auto">
          <div className="rounded-xl border border-[var(--band-red)]/30 bg-[var(--band-red)]/10 p-5 text-foreground">
            <p className="font-medium mb-1">Couldn&apos;t load today&apos;s data</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <p className="text-sm text-muted-foreground mt-2">
              Is the API running? <code>uv run python scripts/run_api.py</code>
            </p>
          </div>
        </div>
      </div>
    )
  }

  if (!data) return null

  const { readiness, strain } = data
  const bandColor = BAND_COLORS[readiness.band]
  // HRV/RHR still drive the score underneath (Francisco's own call,
  // 2026-08-30: "we can use it for calculations... don't need it in the
  // readiness components screen") -- still fully computed and returned by
  // the API, just not one of the rings shown here.
  const visibleComponents = Object.entries(readiness.components).filter(
    ([key]) => key !== "hrv" && key !== "rhr",
  )

  return (
    <div
      className="min-h-full"
      style={{
        backgroundImage: `radial-gradient(ellipse 900px 500px at 50% -10%, ${bandColor}14, transparent)`,
      }}
    >
      <div className="max-w-4xl mx-auto p-6 space-y-3">
        <div className="flex items-baseline justify-between mb-1">
          <h1 className="text-2xl font-semibold text-foreground tracking-tight">Today</h1>
          <p className="text-sm text-muted-foreground tabular-nums">
            {formatHeaderDate(data.date, data.weekday_name)}
          </p>
        </div>

        {/* Recovery + Strain, side by side -- the same peer relationship
            WHOOP gives its own two headline rings (Recovery tells you what
            you can handle, Strain tells you what you did with it). A
            subtle top accent line + faint background wash in the
            readiness band's color mark this as the hero card. */}
        <div className={`${CARD_CLASS} p-5 relative overflow-hidden`}>
          <div
            className="absolute inset-x-0 top-0 h-[3px]"
            style={{ background: `linear-gradient(90deg, transparent, ${bandColor}, transparent)` }}
            aria-hidden
          />
          <div
            className="absolute inset-0 opacity-[0.06] pointer-events-none"
            style={{ background: `radial-gradient(circle at 15% 20%, ${bandColor}, transparent 60%)` }}
            aria-hidden
          />
          <div className="relative grid grid-cols-1 sm:grid-cols-2 gap-6">
            <div className="flex flex-col items-center gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Readiness
              </p>
              <ReadinessRing score={readiness.score} band={readiness.band} />
              <p className="text-xs text-muted-foreground">
                coverage {Math.round(readiness.coverage * 100)}% &middot; confidence:{" "}
                {readiness.confidence}
              </p>
            </div>
            <div className="flex flex-col items-center gap-2">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Strain
              </p>
              <StrainRing strain={strain.strain} zone={strain.zone} />
              <p className="text-xs text-muted-foreground text-center max-w-[220px]">
                {strain.components.length === 0
                  ? "Nothing logged yet today."
                  : strain.components.map((c) => c.description).join(" + ")}
              </p>
            </div>
          </div>

          {visibleComponents.length > 0 && (
            <div className="relative mt-6 pt-5 border-t border-border">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-4">
                Readiness components
              </p>
              <div className="grid grid-cols-3 sm:grid-cols-5 gap-4">
                {visibleComponents.map(([key, comp]) => (
                  <ComponentRing
                    key={key}
                    componentKey={key}
                    score={comp.score}
                    displayRaw={comp.display_raw}
                    excluded={comp.excluded}
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        <SessionCard
          weekdayName={data.weekday_name}
          sessions={data.sessions}
          structuralFlags={data.structural_flags}
        />

        {(data.nutrition_focus || data.trend_observation) && (
          <div className={`${CARD_CLASS} p-4`}>
            <div className="flex items-center gap-2 mb-2">
              <Utensils className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Nutrition &amp; trend
              </p>
            </div>
            <p className="text-sm text-foreground">{data.nutrition_focus}</p>
            {data.trend_observation && (
              <p className="text-sm text-foreground mt-2">
                <span className="font-medium">Trend:</span> {data.trend_observation}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
