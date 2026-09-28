// Mirrors src/health_os/api/trends.py's exact shape.

export interface SeriesPoint {
  date: string
  value: number
}

// Added 2026-09-09: a live-computed average for whatever window is
// currently selected, plus a plain-language read of what it means -- next
// to every chart on this page. `average.value` is always exactly
// `sum(raw)/len(raw)` of that SAME series' own `raw` array (never a
// separately-fetched number, api/trends.py: _window_average()); `meaning`
// reuses the same tone vocabulary as `TrendInsight` below.
export interface WindowAverage {
  value: number | null
  n_days: number
}

export interface WindowMeaning {
  tone: "good" | "neutral" | "bad" | "unknown"
  headline: string
}

// Added 2026-09-28 (Francisco: a real ~2-week gap in weigh-ins followed by
// several real, lower readings made "avg 79.5kg" read misleadingly high --
// it's the plain mean of everything in the window, stale pre-gap readings
// included). `current` is the latest full-history 7-day EWMA point
// (api/trends.py: `_latest_ewma_point()`), the same "where do you actually
// stand" number Today/Comp Prep already use for weight -- deliberately
// window-INDEPENDENT, unlike `average`/`raw`/`smoothed`, which stay exactly
// windowed by the 30/90/365 selector as before. Only present on
// weight_kg/body_fat_pct/fat_mass_kg -- HRV/RHR/sleep/readiness update
// near-daily from the watch, so they don't share this sparse, manually-
// triggered sampling pattern and keep using the plain windowed average.
export interface CurrentValue {
  value: number | null
  as_of: string | null
}

export interface TimeSeries {
  label: string
  raw: SeriesPoint[]
  smoothed: SeriesPoint[]
  average: WindowAverage
  current?: CurrentValue
  meaning: WindowMeaning
}

// A new series (2026-09-09) -- total sleep duration (deep+light+rem minutes,
// awake time excluded) per day, summed from the exact same rows that drive
// the "Sleep stages" stacked-bar chart. No `smoothed` array: this exists
// only to carry the window average/meaning next to that chart, not as a
// second line chart of its own.
export interface SleepTotalSeries {
  label: string
  raw: SeriesPoint[]
  average: WindowAverage
  meaning: WindowMeaning
}

export interface SleepStageRow {
  date: string
  sleep_deep_min?: number
  sleep_light_min?: number
  sleep_rem_min?: number
  sleep_awake_min?: number
  [key: string]: string | number | undefined
}

export interface ReadinessPoint {
  date: string
  value: number
  confidence: string | null
}

export interface ReadinessHistory {
  label: string
  raw: ReadinessPoint[]
  smoothed: SeriesPoint[]
  coverage_summary: Record<string, number>
  average: WindowAverage
  meaning: WindowMeaning
}

// Added 2026-08-30 (Francisco: "tell me things you see in trends... no
// fluff no acronyms"). Plain-English, always present for weight/sleep/hrv/
// rhr (metric: those names); "correlation" entries appear only when a real,
// statistically confirmed pattern exists. tone drives color: good=green,
// bad=red, neutral=gray, unknown=muted (real "not enough data" state, never
// silently neutral), info=blue (a detected pattern, neither good nor bad).
export interface TrendInsight {
  metric: "weight" | "sleep" | "hrv" | "rhr" | "correlation"
  tone: "good" | "neutral" | "bad" | "unknown" | "info"
  headline: string
  detail: string | null
}

// `series` now also carries two body-composition keys added 2026-09-11,
// once the Renpho CSV backfill landed real `body_fat_pct` data (Francisco:
// "is my weight loss/gain coming from fat or muscle"). Both are plain
// `TimeSeries` -- no new interface needed, `Record<string, TimeSeries>`
// already covers them:
//   - "body_fat_pct" -- a real `daily_metrics` column (%), same shape as
//     weight/hrv_overnight_ms/resting_hr above.
//   - "fat_mass_kg" -- NOT a stored column: `weight_kg * body_fat_pct / 100`,
//     computed server-side only for dates with BOTH real inputs that day
//     (api/trends.py: `_build_fat_mass_series()`). Tracked with the exact
//     same EWMA + OLS-trend treatment as weight, so it carries a real
//     `smoothed` line too, not just an average.
// Neither series' `meaning` compares against a target body-fat % -- no such
// number is decided yet (see api/trends.py: `_body_fat_pct_window_meaning()`).
export interface TrendsPayload {
  window_days: number
  series: Record<string, TimeSeries>
  sleep_stages: SleepStageRow[]
  sleep_total: SleepTotalSeries
  readiness: ReadinessHistory
  insights: TrendInsight[]
}

// Mirrors metrics/correlations.py: correlation_result_to_dict()'s exact shape.
export interface CorrelationResult {
  x_name: string
  y_name: string
  description: string | null
  n: number
  rho: number | null
  p_value: number | null
  alpha_used: number | null
  confidence: "insufficient_data" | "not_significant" | "significant"
}
