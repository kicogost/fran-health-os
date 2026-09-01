import { useEffect, useState } from "react"
import {
  Activity,
  Battery,
  BatteryCharging,
  BatteryFull,
  BatteryLow,
  BatteryWarning,
  Bike,
  Dumbbell,
  Footprints,
  Minus,
  Swords,
  TrendingDown,
  TrendingUp,
  TriangleAlert,
  Waves,
  type LucideIcon,
} from "lucide-react"
import { ApiError, fetchTraining } from "@/lib/api"
import { CARD_CLASS, CARD_CLASS_FLAT } from "@/lib/styles"
import type { TrainingInsight, TrainingPayload } from "@/types/training"
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

const SPORT_ICONS: Record<string, LucideIcon> = {
  cycling: Bike,
  ride: Bike,
  bjj: Swords,
  strength_training: Dumbbell,
  weight_training: Dumbbell,
  traditional_strength_training: Dumbbell,
  functional_strength_training: Dumbbell,
  running: Footprints,
  run: Footprints,
  walking: Footprints,
  walk: Footprints,
  swimming: Waves,
  swim: Waves,
}

const FRESHNESS_ICONS: Record<string, LucideIcon> = {
  unknown: Battery,
  fatigued: BatteryWarning,
  tired: BatteryLow,
  normal: Battery,
  fresh: BatteryFull,
  very_fresh: BatteryCharging,
}

const FRESHNESS_LABELS: Record<string, string> = {
  unknown: "Unknown",
  fatigued: "Fatigued",
  tired: "A bit tired",
  normal: "Normal",
  fresh: "Fresh",
  very_fresh: "Very fresh",
}

const TONE_COLOR: Record<TrainingInsight["tone"], string> = {
  good: "var(--band-green)",
  bad: "var(--band-red)",
  neutral: "var(--band-blue)",
  unknown: "var(--muted-foreground)",
}

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
      label: sport.replace(/_/g, " "),
      color: SPORT_COLORS[i % SPORT_COLORS.length],
    })),
  }
}

function formatHours(minutes: number): string {
  const hours = minutes / 60
  return hours >= 10 ? `${hours.toFixed(0)}h` : `${hours.toFixed(1)}h`
}

export function TrainingPage() {
  const [data, setData] = useState<TrainingPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showTechnical, setShowTechnical] = useState(false)

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
              No resting heart rate history exists yet to build this from — this needs at least
              one day of Garmin wellness data synced.
            </p>
          </div>
        </div>
      )}

      {data.has_load_data && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <InsightHero insight={data.insights.freshness} band={data.insights.freshness.band} />
            <InsightHero insight={data.insights.fitness_trend} />
          </div>

          <WeekSummaryCard summary={data.weekly_summary} consistency={data.insights.consistency} />

          <div className={`${CARD_CLASS_FLAT} p-4`}>
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
              Effort over time, by sport
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              Every real session with a heart-rate reading (or a logged BJJ class), going back as
              far as there's data — taller bars mean more effort that day.
            </p>
            {sportData.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing to show yet.</p>
            ) : (
              <StackedBarChart data={sportData} bars={sportBars} showLegend />
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

      {data.has_load_data && (
        <div className={`${CARD_CLASS_FLAT} p-4`}>
          <button
            type="button"
            onClick={() => setShowTechnical((v) => !v)}
            className="rounded-full border border-border px-3 py-1 text-xs font-medium uppercase tracking-wider text-muted-foreground hover:text-foreground hover:border-muted-foreground/50 transition-colors"
          >
            {showTechnical ? "Hide" : "Show"} technical detail
          </button>
          {showTechnical && (
            // Surface-ladder tone shift (Linear: depth via a lighter sub-
            // panel, not a shadow) instead of just sitting flush on the
            // flat card above -- one step up from --card, same as the rest
            // of this flat-card family.
            <div className="mt-4 space-y-4 rounded-lg bg-accent/40 p-4">
              <p className="text-xs text-muted-foreground">
                The numbers behind the plain-English cards above, for anyone who wants to check
                the math (design principle: every number here should be traceable).
              </p>
              <div>
                <p className="text-xs text-muted-foreground mb-2">
                  Fitness (blue) vs. fatigue (red) trend, and freshness (shaded bars) — the
                  underlying Banister impulse-response model.
                </p>
                <CtlAtlTsbChart data={data.ctl_atl_tsb} />
                {data.tsb_zscore?.confidence === "full" && (
                  <p className="text-xs text-muted-foreground mt-2">
                    Freshness z-score vs. own trailing 90-day distribution:{" "}
                    {data.tsb_zscore.z_score?.toFixed(2)}
                  </p>
                )}
                {data.tsb_zscore?.confidence === "full" &&
                  data.tsb_zscore.z_score != null &&
                  Math.abs(data.tsb_zscore.z_score) >= 2 && (
                    <p className="text-xs text-[var(--band-amber)] mt-1">
                      A swing this big isn&apos;t necessarily a problem on its own -- no study
                      has validated what size of freshness swing should be considered
                      concerning, for any sport (see ADR 0003/0007). Shown for transparency,
                      not as an alarm.
                    </p>
                  )}
              </div>
              {data.monotony_strain?.confidence === "full" && (
                <div className="grid grid-cols-3 gap-3">
                  <Stat
                    label="Weekly load (raw)"
                    value={data.monotony_strain.weekly_load?.toFixed(0) ?? "--"}
                  />
                  <Stat
                    label="Monotony"
                    value={data.monotony_strain.monotony?.toFixed(2) ?? "--"}
                    flag={data.monotony_strain.flag_high_monotony}
                  />
                  <Stat label="Strain" value={data.monotony_strain.strain?.toFixed(0) ?? "--"} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Freshness or fitness-trend, as a big icon + plain sentence -- the primary
 * view Francisco asked for (2026-08-30): "no fluff no acronyms," CTL/ATL/
 * TSB never named here at all. `band` (freshness only) picks a battery-style
 * icon; fitness-trend uses a simple up/flat/down arrow instead.
 */
function InsightHero({ insight, band }: { insight: TrainingInsight; band?: string }) {
  const color = TONE_COLOR[insight.tone]
  const Icon =
    band !== undefined
      ? (FRESHNESS_ICONS[band] ?? Battery)
      : insight.headline.toLowerCase().includes("building")
        ? TrendingUp
        : insight.headline.toLowerCase().includes("dipped")
          ? TrendingDown
          : Minus

  return (
    <div className={`${CARD_CLASS} p-5`}>
      <div className="flex items-center gap-4">
        <div
          className="flex items-center justify-center h-14 w-14 rounded-full shrink-0"
          style={{ backgroundColor: `color-mix(in srgb, ${color} 15%, transparent)` }}
        >
          <Icon className="h-7 w-7" strokeWidth={2} style={{ color }} />
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-1">
            {band !== undefined ? "Freshness" : "Fitness trend"}
            {band !== undefined && (
              <span className="normal-case font-normal"> · {FRESHNESS_LABELS[band]}</span>
            )}
          </p>
          <p className="text-sm text-foreground leading-snug">{insight.headline}</p>
          {insight.detail && (
            <p className="text-xs text-muted-foreground mt-1 leading-snug">{insight.detail}</p>
          )}
        </div>
      </div>
    </div>
  )
}

function WeekSummaryCard({
  summary,
  consistency,
}: {
  summary: TrainingPayload["weekly_summary"]
  consistency: TrainingInsight
}) {
  return (
    <div className={`${CARD_CLASS} p-4`}>
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
        This week
      </p>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">
            {summary.session_count}
          </p>
          <p className="text-xs text-muted-foreground">
            session{summary.session_count === 1 ? "" : "s"}
          </p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">
            {formatHours(summary.total_minutes)}
          </p>
          <p className="text-xs text-muted-foreground">total time trained</p>
        </div>
      </div>
      {summary.by_sport.length > 0 && (
        <div className="flex flex-wrap gap-3 mb-3">
          {summary.by_sport.map((row) => {
            const Icon = SPORT_ICONS[row.sport] ?? Activity
            return (
              <div
                key={row.sport}
                className="flex items-center gap-1.5 text-xs text-muted-foreground"
              >
                <Icon className="h-3.5 w-3.5" strokeWidth={2} />
                <span className="text-foreground">{row.sport.replace(/_/g, " ")}</span>
                <span>· {formatHours(row.minutes)}</span>
              </div>
            )
          })}
        </div>
      )}
      <p className="text-xs text-muted-foreground pt-3 border-t border-border">
        {consistency.headline}
        {consistency.detail && <span> {consistency.detail}</span>}
      </p>
    </div>
  )
}

function Stat({ label, value, flag }: { label: string; value: string; flag?: boolean }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-semibold tabular-nums tracking-tight text-foreground">
        {value}
        {flag && <span className="text-[var(--band-amber)] text-sm ml-1">high</span>}
      </p>
    </div>
  )
}
