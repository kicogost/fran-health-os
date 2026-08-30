import { useEffect, useState } from "react"
import { Activity, Gauge, HeartPulse, Moon, Scale, Search } from "lucide-react"
import { ApiError, fetchCorrelations, fetchTrends } from "@/lib/api"
import { CARD_CLASS } from "@/lib/styles"
import type { CorrelationResult, TrendsPayload } from "@/types/trends"
import { TrendChart } from "@/components/charts/TrendChart"
import { StackedBarChart } from "@/components/charts/StackedBarChart"

const WINDOW_OPTIONS = [30, 90, 365] as const

const SLEEP_STAGE_BARS = [
  { key: "sleep_deep_min", label: "Deep", color: "var(--band-green)" },
  { key: "sleep_light_min", label: "Light", color: "var(--band-blue)" },
  { key: "sleep_rem_min", label: "REM", color: "#a371f7" },
  { key: "sleep_awake_min", label: "Awake", color: "var(--band-red)" },
]

export function TrendsPage() {
  const [windowDays, setWindowDays] = useState<(typeof WINDOW_OPTIONS)[number]>(90)
  const [data, setData] = useState<TrendsPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [correlations, setCorrelations] = useState<CorrelationResult[] | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchTrends(windowDays)
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
  }, [windowDays])

  useEffect(() => {
    // Not windowed like the charts above -- correlations use the FULL
    // available history regardless of the 30/90/365d selector, since more
    // real data only helps the sample-size gate, never hurts it.
    let cancelled = false
    fetchCorrelations()
      .then((results) => {
        if (!cancelled) setCorrelations(results)
      })
      .catch(() => {
        if (!cancelled) setCorrelations(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-semibold text-foreground tracking-tight">Trends</h1>
        <div className="flex gap-1 rounded-lg border border-border p-1">
          {WINDOW_OPTIONS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindowDays(w)}
              className={[
                "px-3 py-1 text-sm rounded-md transition-colors",
                windowDays === w
                  ? "bg-accent text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground",
              ].join(" ")}
            >
              {w}d
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className={`${CARD_CLASS} p-5 border-[var(--band-red)]/30`}>
          <p className="text-sm text-foreground">{error}</p>
        </div>
      )}

      {loading && !data && <p className="text-muted-foreground p-4">Loading...</p>}

      {data && (
        <>
          <ChartCard
            icon={Gauge}
            title="Readiness score"
            hasData={!!data.readiness.raw.length}
          >
            {data.readiness.raw.length > 0 && (
              <>
                <TrendChart
                  raw={data.readiness.raw}
                  smoothed={data.readiness.smoothed}
                  color="var(--band-blue)"
                />
                <p className="text-xs text-muted-foreground mt-2">
                  {data.readiness.raw.length} day{data.readiness.raw.length === 1 ? "" : "s"} shown —{" "}
                  {Object.entries(data.readiness.coverage_summary)
                    .map(([confidence, count]) => `${count} ${confidence}`)
                    .join(", ")}{" "}
                  confidence. Partial mostly means no wellness log that day — never invented as full.
                </p>
              </>
            )}
          </ChartCard>

          <ChartCard
            icon={Scale}
            title="Weight (kg)"
            hasData={!!data.series.weight_kg?.raw.length}
          >
            {data.series.weight_kg && (
              <TrendChart
                raw={data.series.weight_kg.raw}
                smoothed={data.series.weight_kg.smoothed}
                color="var(--band-blue)"
                unit="kg"
              />
            )}
          </ChartCard>

          <ChartCard
            icon={HeartPulse}
            title="HRV overnight (ms)"
            hasData={!!data.series.hrv_overnight_ms?.raw.length}
          >
            {data.series.hrv_overnight_ms && (
              <TrendChart
                raw={data.series.hrv_overnight_ms.raw}
                smoothed={data.series.hrv_overnight_ms.smoothed}
                color="var(--band-green)"
                unit="ms"
              />
            )}
          </ChartCard>

          <ChartCard
            icon={Activity}
            title="Resting heart rate (bpm)"
            hasData={!!data.series.resting_hr?.raw.length}
          >
            {data.series.resting_hr && (
              <TrendChart
                raw={data.series.resting_hr.raw}
                smoothed={data.series.resting_hr.smoothed}
                color="var(--band-amber)"
                unit="bpm"
              />
            )}
          </ChartCard>

          <ChartCard
            icon={Moon}
            title="Sleep stages (minutes)"
            hasData={data.sleep_stages.length > 0}
          >
            <StackedBarChart data={data.sleep_stages} bars={SLEEP_STAGE_BARS} />
          </ChartCard>

          {correlations && <CorrelationsCard results={correlations} />}
        </>
      )}
    </div>
  )
}

/** Detected patterns -- metrics/correlations.py's Spearman-rank engine,
 * gated on real sample size (n>=30) and Bonferroni-corrected across every
 * pair tested, so this only ever shows a "significant" result backed by
 * actual statistics -- never a same-week coincidence dressed up as insight.
 * Most days this will show "not enough data yet," which is the honest,
 * expected state until wellness logging accumulates -- not a bug.
 */
function CorrelationsCard({ results }: { results: CorrelationResult[] }) {
  const significant = results.filter((r) => r.confidence === "significant")
  const tested = results.filter((r) => r.confidence !== "insufficient_data")

  return (
    <div className={`${CARD_CLASS} p-4`}>
      <div className="flex items-center gap-2 mb-3">
        <Search className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Detected patterns
        </p>
      </div>

      {significant.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No statistically significant patterns yet ({tested.length} of {results.length} candidate
          pairs have enough paired days to test — each needs 30+ real days logged on both sides).
          Keep logging daily wellness and this fills in on its own; nothing gets claimed from a
          short streak.
        </p>
      ) : (
        <div className="space-y-3">
          {significant.map((r) => (
            <div key={`${r.x_name}-${r.y_name}`} className="text-sm">
              <p className="text-foreground">{r.description}</p>
              <p className="text-xs text-muted-foreground">
                rho = {r.rho?.toFixed(2)}, n = {r.n} days, p = {r.p_value?.toFixed(4)} (Bonferroni-
                corrected threshold {r.alpha_used?.toFixed(4)})
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ChartCard({
  icon: Icon,
  title,
  hasData,
  children,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>
  title: string
  hasData: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`${CARD_CLASS} p-4`}>
      <div className="flex items-center gap-2 mb-3">
        <Icon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {title}
        </p>
      </div>
      {hasData ? children : <p className="text-sm text-muted-foreground">No data in this window.</p>}
    </div>
  )
}
