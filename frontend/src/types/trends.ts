// Mirrors src/health_os/api/trends.py's exact shape.

export interface SeriesPoint {
  date: string
  value: number
}

export interface TimeSeries {
  label: string
  raw: SeriesPoint[]
  smoothed: SeriesPoint[]
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

export interface TrendsPayload {
  window_days: number
  series: Record<string, TimeSeries>
  sleep_stages: SleepStageRow[]
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
