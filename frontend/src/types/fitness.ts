import type { WindowMeaning } from "@/types/trends"

export type Vo2maxStatus = "measured" | "estimate" | "low_confidence" | "too_old" | "insufficient_data"

export interface Vo2maxPoint {
  date: string
  value: number
  low: number
  high: number
  status: Vo2maxStatus
}

export interface Vo2maxPayload {
  as_of: string
  hr_max: number
  latest_measurement: { date: string; value: number; days_ago: number } | null
  current: {
    date: string
    status: Vo2maxStatus
    value: number | null
    low?: number
    high?: number
    weeks_since_anchor?: number
  }
  measurements: { date: string; value: number }[]
  estimate_series: Vo2maxPoint[]
  calibration: {
    personal_factor: number
    sigma_cal: number
    n_anchors: number
  } | null
  weight_only: { value: number; weight_at_anchor_kg: number; weight_now_kg: number } | null
  context: {
    bjj_reference_range: [number, number]
    rhr_28d_at_anchor?: number | null
    rhr_28d_now: number | null
    hrv_28d_at_anchor?: number | null
    hrv_28d_now: number | null
  }
  bjj_recovery: { date: string; avg_drop_bpm: number }[]
  meaning: WindowMeaning
}
