// Mirrors src/health_os/api/comp_prep.py's exact shape.

export interface CompPrepGoal {
  name: string
  date: string
  weight_limit_kg: number
}

export interface CompCountdown {
  current_weight_kg: number
  weight_limit_kg: number
  kg_remaining: number
  days_remaining: number
  weeks_remaining: number
  required_kg_per_week: number | null
  actual_kg_per_week: number | null
  red_flag: boolean
}

export interface WeightTrend {
  slope_kg_per_week: number | null
  ci_low_kg_per_week: number | null
  ci_high_kg_per_week: number | null
  n: number
  window_days: number
  confidence: string
}

export interface WeightPoint {
  date: string
  value: number
}

export interface Projection {
  mid: WeightPoint[]
  ci_low: WeightPoint[]
  ci_high: WeightPoint[]
}

export interface CompPrepPayload {
  goal: CompPrepGoal
  has_weight_data: boolean
  countdown?: CompCountdown
  trend?: WeightTrend
  weight_raw?: WeightPoint[]
  weight_ewma?: WeightPoint[]
  required_path?: WeightPoint[]
  projection?: Projection | null
}
