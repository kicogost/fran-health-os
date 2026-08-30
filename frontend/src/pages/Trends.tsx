import { useEffect, useState } from "react"
import { Activity, Gauge, HeartPulse, Moon, Scale, Search, TriangleAlert } from "lucide-react"
import { ApiError, fetchCorrelations, fetchTrends } from "@/lib/api"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import type { CorrelationResult, TrendInsight, TrendsPayload } from "@/types/trends"
import { TrendChart } from "@/components/charts/TrendChart"
import { StackedBarChart } from "@/components/charts/StackedBarChart"

const WINDOW_OPTIONS = [30, 90, 365] as const

const SLEEP_STAGE_BARS = [
  { key: "sleep_deep_min", label: "Deep", color: "var(--band-green)" },
  { key: "sleep_light_min", label: "Light", color: "var(--band-blue)" },
  { key: "sleep_rem_min", label: "REM", color: "#a371f7" },
  { key: "sleep_awake_min", label: "Awake", color: "var(--band-red)" },
]

const INSIGHT_ICONS: Record<TrendInsight["metric"], React.ComponentType<{ className?: string; strokeWidth?: number }>> = {
  weight: Scale,
  sleep: Moon,
  hrv: HeartPulse,
  rhr: Activity,
  correlation: Search,
}

const TONE_COLOR: Record<TrendInsight["tone"], string> = {
  good: "var(--band-green)",
  bad: "var(--band-red)",
  neutral: "var(--band-blue)",
  info: "var(--band-blue)",
  unknown: "var(--muted-foreground)",
}

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
    // Only used here for the honest "N of M pairs have enough data yet"
    // count when nothing significant has been found -- the confirmed
    // patterns themselves come from data.insights (built server-side from
    // the same underlying engine), not a second parse of this call.
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

  const hasConfirmedCorrelation = data?.insights.some((i) => i.metric === "correlation") ?? false
  const testedCorrelations = correlations?.filter((r) => r.confidence !== "insufficient_data").length ?? 0

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-semibold text-foreground tracking-tight">Trends</h1>
        <div className="flex gap-1 rounded-full border border-border p-1">
          {WINDOW_OPTIONS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWindowDays(w)}
              className={[
                "px-3 py-1 text-sm rounded-full transition-colors",
                windowDays === w
                  ? "bg-[var(--band-blue)] text-[#0a0a0b] font-medium"
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
          <div className="grid gap-3 sm:grid-cols-2">
            {data.insights.map((insight, i) => (
              <InsightCard key={i} insight={insight} />
            ))}
          </div>

          {!hasConfirmedCorrelation && correlations && (
            <p className="text-xs text-muted-foreground px-1">
              No confirmed links between your metrics yet ({testedCorrelations} of{" "}
              {correlations.length} candidate comparisons have enough logged data to test — each
              needs 30+ real days on both sides). Keep logging daily wellness and this fills in on
              its own.
            </p>
          )}

          <ChartCard icon={Gauge} title="Readiness score" hasData={!!data.readiness.raw.length}>
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

          <ChartCard icon={Scale} title="Weight (kg)" hasData={!!data.series.weight_kg?.raw.length}>
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

          <ChartCard icon={Moon} title="Sleep stages (minutes)" hasData={data.sleep_stages.length > 0}>
            <StackedBarChart data={data.sleep_stages} bars={SLEEP_STAGE_BARS} />
          </ChartCard>
        </>
      )}
    </div>
  )
}

/** One plain-English takeaway -- the headline of the Trends page, per
 * Francisco's own ask (2026-08-30): "tell me things you see in trends...
 * no fluff no acronyms." Color and icon are the only "visual jargon" here;
 * the sentence itself is always the plain output of
 * metrics/insights.py, never a raw number.
 */
function InsightCard({ insight }: { insight: TrendInsight }) {
  const Icon = insight.tone === "unknown" ? TriangleAlert : INSIGHT_ICONS[insight.metric]
  const color = TONE_COLOR[insight.tone]
  return (
    <div
      className={`${CARD_CLASS} p-4 border-l-2`}
      style={{ borderLeftColor: color }}
    >
      <div className="flex items-start gap-2.5">
        <Icon
          className="h-4 w-4 mt-0.5 shrink-0"
          strokeWidth={2.25}
          style={{ color: insight.tone === "unknown" ? "var(--muted-foreground)" : color }}
        />
        <div>
          <p className="text-sm text-foreground leading-snug">{insight.headline}</p>
          {insight.detail && (
            <p className="text-xs text-muted-foreground mt-1 leading-snug">{insight.detail}</p>
          )}
        </div>
      </div>
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
    <div className={`${CARD_CLASS_FLAT} p-4`}>
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
