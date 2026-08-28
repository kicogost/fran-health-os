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

export interface TrendsPayload {
  window_days: number
  series: Record<string, TimeSeries>
  sleep_stages: SleepStageRow[]
}
