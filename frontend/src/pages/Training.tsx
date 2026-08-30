import { useEffect, useState } from "react"
import { Activity, Dumbbell, Gauge, TriangleAlert } from "lucide-react"
import { ApiError, fetchTraining } from "@/lib/api"
import { CARD_CLASS } from "@/lib/styles"
import type { TrainingPayload } from "@/types/training"
import { CtlAtlTsbChart } from "@/components/charts/CtlAtlTsbChart"
import { StackedBarChart } from "@/components/charts/StackedBarChart"

// Same palette rotation for however many distinct sports show up -- not
// hardcoded per sport name, since which sports have real avg_hr data varies
// by account and changes over time.
const SPORT_COLORS = [
  "var(--band-blue)",
  "var(--band-green)",
  "var(--band-amber)",
  "var(--band-red)",
  "#a371f7",
  "#8d8d8d",
]

function pivotLoadBySport(rows: TrainingPayload["load_by_sport"]) {
  const sports = Array.from(new Set(rows.map((r) => r.sport)))
  const byDate = new Map<string, Record<string, string | number>>()
  for (const row of rows) {
    const entry = byDate.get(row.date) ?? { date: row.date }
    entry[row.sport] = row.load
    byDate.set(row.date, entry)
  }
  return {
    data: Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date))),
    bars: sports.map((sport, i) => ({
      key: sport,
      label: sport,
      color: SPORT_COLORS[i % SPORT_COLORS.length],
    })),
  }
}

export function TrainingPage() {
  const [data, setData] = useState<TrainingPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchTraining()
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

  const { data: sportData, bars: sportBars } = pivotLoadBySport(data.load_by_sport)
  const mono = data.monotony_strain

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-3">
      <h1 className="text-2xl font-semibold text-foreground tracking-tight mb-1">Training</h1>

      {!data.has_load_data && (
        <div className={`${CARD_CLASS} p-5 border-[var(--band-amber)]/30`}>
          <div className="flex items-start gap-2">
            <TriangleAlert
              className="h-4 w-4 text-[var(--band-amber)] mt-0.5 shrink-0"
              strokeWidth={2.25}
            />
            <p className="text-sm text-foreground">
              No resting heart rate history exists yet to build a load series from — this needs
              at least one day of Garmin wellness data synced (<code>scripts/sync.py</code>).
            </p>
          </div>
        </div>
      )}

      {data.has_load_data && (
        <>
          <div className={`${CARD_CLASS} p-4`}>
            <div className="flex items-center gap-2 mb-3">
              <Gauge className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                CTL / ATL / TSB
              </p>
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              <span className="text-[var(--band-blue)]">CTL (blue)</span> is your longer-term
              fitness — it rises and fades slowly. <span className="text-[var(--band-red)]">
                ATL (red)
              </span>{" "}
              is your recent fatigue — it reacts fast to a hard week. TSB (the shaded bars) is
              CTL minus ATL: positive means you&apos;re fresher than usual, negative means more
              run-down than usual.
            </p>
            <CtlAtlTsbChart data={data.ctl_atl_tsb} />
            {data.tsb_zscore?.confidence === "full" && (
              <p className="text-xs text-muted-foreground mt-2">
                Latest TSB z-score vs. own trailing 90-day distribution:{" "}
                {data.tsb_zscore.z_score?.toFixed(2)}
              </p>
            )}
            {data.tsb_zscore?.confidence === "full" &&
              Math.abs(data.tsb_zscore.z_score ?? 0) >= 2 && (
                <p className="text-xs text-[var(--band-amber)] mt-1">
                  This is a real, large swing relative to your own recent history — but TSB has
                  no universally validated &quot;how much is too much&quot; threshold (part of
                  why it was removed from the readiness score itself, ADR 0007). Read it as a
                  relative trend, not a fixed-scale verdict.
                </p>
              )}
          </div>

          <div className={`${CARD_CLASS} p-4`}>
            <div className="flex items-center gap-2 mb-3">
              <Activity className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Monotony / strain (trailing 7 days)
              </p>
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              Monotony is how same-y your daily load has been this week (high = you did roughly
              the same amount every day, no easy/hard variation). Strain is weekly load ×
              monotony — two weeks with identical total volume can feel very different in
              recovery terms if one of them was more repetitive.
            </p>
            {!mono || mono.confidence === "insufficient_data" ? (
              <p className="text-sm text-muted-foreground">Not enough days of load data yet (need 7).</p>
            ) : mono.confidence === "undefined_zero_variance" ? (
              <p className="text-sm text-muted-foreground">
                Weekly load: {mono.weekly_load?.toFixed(0)}. Monotony undefined (zero variance this
                week).
              </p>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Weekly load" value={mono.weekly_load?.toFixed(0) ?? "--"} />
                <Stat
                  label="Monotony"
                  value={mono.monotony?.toFixed(2) ?? "--"}
                  flag={mono.flag_high_monotony}
                />
                <Stat label="Strain" value={mono.strain?.toFixed(0) ?? "--"} />
              </div>
            )}
          </div>

          <div className={`${CARD_CLASS} p-4`}>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
              Load by day and sport
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              Estimated from heart rate wherever a session has one (rides, runs, recorded BJJ,
              strength) — logged BJJ classes without a heart-rate recording use RPE × duration
              instead. A day with real training but no bar just means neither of those was
              available for it yet.
            </p>
            {sportData.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing to break down by sport yet in this window.
              </p>
            ) : (
              <StackedBarChart data={sportData} bars={sportBars} />
            )}
          </div>
        </>
      )}

      <div className={`${CARD_CLASS} p-4`}>
        <div className="flex items-center gap-2 mb-3">
          <Dumbbell className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Calisthenics
          </p>
        </div>
        {data.calisthenics.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing logged yet — use the Log page&apos;s Calisthenics tab after your next
            Monday/Wednesday session.
          </p>
        ) : (
          <div className="space-y-3">
            {data.calisthenics.map((session, i) => (
              <div key={i}>
                <p className="text-sm text-foreground font-medium">
                  {session.date} — {session.session_type}
                  {session.session_rpe != null && ` (RPE ${session.session_rpe})`}
                </p>
                {session.exercises.length === 0 ? (
                  <p className="text-xs text-muted-foreground">no per-exercise detail logged</p>
                ) : (
                  session.exercises.map((ex, j) => (
                    <p key={j} className="text-xs text-muted-foreground">
                      {ex.exercise}: {ex.sets}x{ex.reps}
                      {ex.added_weight_kg ? ` @ +${ex.added_weight_kg}kg` : ""}
                    </p>
                  ))
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, flag }: { label: string; value: string; flag?: boolean }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold tabular-nums text-foreground">
        {value}
        {flag && <span className="text-[var(--band-amber)] text-sm ml-1">high</span>}
      </p>
    </div>
  )
}
