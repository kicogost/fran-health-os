import { useEffect, useState } from "react"
import { ApiError, fetchToday } from "@/lib/api"
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
      <div className="p-8 max-w-lg">
        <div className="rounded-xl border border-[var(--band-red)]/30 bg-[var(--band-red)]/10 p-5 text-foreground">
          <p className="font-medium mb-1">Couldn&apos;t load today&apos;s data</p>
          <p className="text-sm text-muted-foreground">{error}</p>
          <p className="text-sm text-muted-foreground mt-2">
            Is the API running? <code>uv run python scripts/run_api.py</code>
          </p>
        </div>
      </div>
    )
  }

  if (!data) return null

  const { readiness, sleep, weight, comp_countdown: compCountdown } = data

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-2xl font-semibold text-foreground mb-2">Today</h1>

      {/* Readiness: central ring + component breakdown */}
      <div className="rounded-xl border border-border bg-card p-6">
        <div className="flex flex-col md:flex-row items-center gap-8">
          <div className="flex flex-col items-center gap-2 shrink-0">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Readiness
            </p>
            <ReadinessRing score={readiness.score} band={readiness.band} />
            <p className="text-xs text-muted-foreground">
              as of {data.date} &middot; coverage {Math.round(readiness.coverage * 100)}% &middot;
              confidence: {readiness.confidence}
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
              <div className="flex flex-wrap gap-6 justify-center md:justify-start">
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

      <div className="flex flex-col sm:flex-row gap-4">
        <StatCard
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
          label="Weight (7-day EWMA)"
          value={weight ? `${weight.ewma_kg.toFixed(2)} kg` : "--"}
          caption={
            weight
              ? `last real weigh-in: ${weight.latest_kg.toFixed(2)} kg on ${weight.latest_date}`
              : "No weight data yet."
          }
        />
        <StatCard
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
              Required: <span className="font-medium">{compCountdown.required_kg_per_week.toFixed(2)} kg/wk</span>
              {compCountdown.red_flag && (
                <span className="text-[var(--band-amber)]"> &nbsp;⚠️ over 0.7 red line</span>
              )}
            </p>
          )}
        </StatCard>
      </div>

      {(data.nutrition_focus || data.trend_observation) && (
        <div className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-2">
            Nutrition &amp; trend
          </p>
          <p className="text-sm text-foreground">{data.nutrition_focus}</p>
          {data.trend_observation && (
            <p className="text-sm text-foreground mt-2">
              <span className="font-medium">Trend:</span> {data.trend_observation}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
