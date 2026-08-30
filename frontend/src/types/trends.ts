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

export interface TrendsPayload {
  window_days: number
  series: Record<string, TimeSeries>
  sleep_stages: SleepStageRow[]
  readiness: ReadinessHistory
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
