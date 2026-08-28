import { useEffect, useState } from "react"
import { TriangleAlert, Trophy } from "lucide-react"
import { ApiError, fetchCompPrep } from "@/lib/api"
import { CARD_CLASS } from "@/lib/styles"
import type { CompPrepPayload } from "@/types/compPrep"
import { StatCard } from "@/components/today/StatCard"
import { WeightTrajectoryChart } from "@/components/charts/WeightTrajectoryChart"

export function CompPrepPage() {
  const [data, setData] = useState<CompPrepPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchCompPrep()
      .then((payload) => {
        if (!cancelled) setData(payload)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not reach the API.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <p className="text-muted-foreground p-8">Loading...</p>
  if (error)
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className={`${CARD_CLASS} p-5 border-[var(--band-red)]/30`}>
          <p className="text-sm text-foreground">{error}</p>
        </div>
      </div>
    )
  if (!data) return null

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center gap-2 mb-1">
        <Trophy className="h-5 w-5 text-[var(--band-amber)]" strokeWidth={2} />
        <div>
          <h1 className="text-2xl font-semibold text-foreground tracking-tight">Comp Prep</h1>
          <p className="text-xs text-muted-foreground">
            {data.goal.name} — {data.goal.date} — {data.goal.weight_limit_kg} kg division
          </p>
        </div>
      </div>

      {!data.has_weight_data ? (
        <div className={`${CARD_CLASS} p-5`}>
          <p className="text-sm text-muted-foreground">No weight data yet.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              icon={Trophy}
              label="Current (EWMA)"
              value={`${data.countdown!.current_weight_kg.toFixed(2)} kg`}
            />
            <StatCard
              icon={Trophy}
              label="kg to lose"
              value={data.countdown!.kg_remaining.toFixed(2)}
            />
            <StatCard
              icon={Trophy}
              label="Weeks left"
              value={data.countdown!.weeks_remaining.toFixed(1)}
            />
            <StatCard
              icon={Trophy}
              label="Required kg/wk"
              value={
                data.countdown!.required_kg_per_week != null
                  ? data.countdown!.required_kg_per_week.toFixed(2)
                  : "—"
              }
            >
              {data.countdown!.red_flag && (
                <p className="inline-flex items-center gap-1 text-xs text-[var(--band-amber)] mt-1">
                  <TriangleAlert className="h-3 w-3" strokeWidth={2.25} />
                  over red line
                </p>
              )}
            </StatCard>
          </div>

          {data.trend!.confidence === "insufficient_data" ? (
            <p className="text-xs text-muted-foreground">
              Trend slope: insufficient data (needs 3+ real weigh-ins in the trailing 21 days).
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Actual trend: {data.countdown!.actual_kg_per_week?.toFixed(2)} kg/wk (95% CI [
              {(-data.trend!.ci_high_kg_per_week!).toFixed(2)},{" "}
              {(-data.trend!.ci_low_kg_per_week!).toFixed(2)}], n={data.trend!.n})
            </p>
          )}

          <div className={`${CARD_CLASS} p-4`}>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
              Weight trajectory vs. required path
            </p>
            <WeightTrajectoryChart
              weightRaw={data.weight_raw}
              weightEwma={data.weight_ewma}
              requiredPath={data.required_path}
              projection={data.projection ?? null}
              weightLimitKg={data.goal.weight_limit_kg}
            />
            {data.trend!.confidence === "insufficient_data" && (
              <p className="text-xs text-muted-foreground mt-2">
                Projection band not shown — not enough recent weigh-ins for a trend (design
                principle 6: never show a confidence interval from too few points).
              </p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
