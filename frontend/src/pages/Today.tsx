import { useEffect, useState } from "react"
import { Moon, Scale, Target, TriangleAlert, Utensils } from "lucide-react"
import { ApiError, fetchToday } from "@/lib/api"
import { BAND_COLORS } from "@/lib/band"
import { CARD_CLASS } from "@/lib/styles"
import type { TodayPayload } from "@/types/today"
import { ReadinessRing } from "@/components/today/ReadinessRing"
import { ComponentRing } from "@/components/today/ComponentRing"
import { SessionCard } from "@/components/today/SessionCard"
import { StatCard } from "@/components/today/StatCard"

function formatMinutes(min: number): string {
  const hours = Math.floor(min / 60)
  const mins = Math.round(min % 60)
  return `${hours}h ${mins}m`
}

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

  const { readiness, sleep, weight, comp_countdown: compCountdown } = data
  const bandColor = BAND_COLORS[readiness.band]

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

        {/* Readiness: central ring + component breakdown. A subtle top accent
            line + faint background wash in the band's own color mark this as
            the hero card -- everything else on the page is downstream of it. */}
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
          <div className="relative flex flex-col md:flex-row items-center gap-8">
            <div className="flex flex-col items-center gap-2 shrink-0">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Readiness
              </p>
              <ReadinessRing score={readiness.score} band={readiness.band} />
              <p className="text-xs text-muted-foreground">
                coverage {Math.round(readiness.coverage * 100)}% &middot; confidence:{" "}
                {readiness.confidence}
              </p>
            </div>
            <div className="flex-1 w-full">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-4">
                Components
              </p>
              {Object.keys(readiness.components).length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No components have enough data yet for a readiness score.
                </p>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-4">
                  {Object.entries(readiness.components).map(([key, comp]) => (
                    <ComponentRing key={key} componentKey={key} score={comp.score} />
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <SessionCard
          weekdayName={data.weekday_name}
          sessions={data.sessions}
          structuralFlags={data.structural_flags}
        />

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <StatCard
            icon={Moon}
            label="Sleep (last night)"
            value={sleep ? formatMinutes(sleep.total_min) : "--"}
            caption={
              sleep
                ? [
                    sleep.deep_min != null && `deep ${Math.round(sleep.deep_min)}m`,
                    sleep.light_min != null && `light ${Math.round(sleep.light_min)}m`,
                    sleep.rem_min != null && `rem ${Math.round(sleep.rem_min)}m`,
                    sleep.awake_min != null && `awake ${Math.round(sleep.awake_min)}m`,
                  ]
                    .filter(Boolean)
                    .join(" · ")
                : "No sleep data for the most recent day."
            }
          />
          <StatCard
            icon={Scale}
            label="Weight (7-day EWMA)"
            value={weight ? `${weight.ewma_kg.toFixed(2)} kg` : "--"}
            caption={
              weight
                ? `last real weigh-in: ${weight.latest_kg.toFixed(2)} kg on ${weight.latest_date}`
                : "No weight data yet."
            }
          />
          <StatCard
            icon={Target}
            label="Comp countdown"
            value={compCountdown ? `${compCountdown.kg_remaining.toFixed(2)} kg to lose` : "--"}
            caption={
              compCountdown
                ? `${compCountdown.weeks_remaining.toFixed(1)} weeks left`
                : "No weight data yet."
            }
          >
            {compCountdown?.required_kg_per_week != null && (
              <p className="text-sm text-foreground mt-2">
                Required:{" "}
                <span className="font-medium">
                  {compCountdown.required_kg_per_week.toFixed(2)} kg/wk
                </span>
                {compCountdown.red_flag && (
                  <span className="inline-flex items-center gap-1 text-[var(--band-amber)] ml-1.5">
                    <TriangleAlert className="h-3.5 w-3.5" strokeWidth={2.25} />
                    over 0.7 red line
                  </span>
                )}
              </p>
            )}
          </StatCard>
        </div>

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
