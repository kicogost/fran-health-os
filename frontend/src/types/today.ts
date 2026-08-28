// Mirrors src/health_os/api/today.py: build_today_payload()'s exact shape.
// Keep these two in sync by hand -- no codegen in this project (deliberately
// small, personal-scale; not worth an OpenAPI-codegen pipeline for one page).

export type ReadinessBand = "no_data" | "red" | "amber" | "green"

export interface ReadinessComponent {
  raw: number | Record<string, number | null>
  score: number
  weight_used: number
}

export interface Readiness {
  score: number | null
  band: ReadinessBand
  coverage: number
  confidence: string
  components: Record<string, ReadinessComponent>
}

export interface Session {
  type: string
  subtype?: string
  format?: string
  notes?: string
  label: string
  instruction: string
}

export interface StructuralFlags {
  downgrade_to_rest: boolean
  hrv_sustained_low: boolean
  tsb_persistently_negative: boolean
  monotony_strain: boolean
}

export interface Sleep {
  total_min: number
  deep_min: number | null
  light_min: number | null
  rem_min: number | null
  awake_min: number | null
}

export interface Weight {
  ewma_kg: number
  latest_kg: number
  latest_date: string
}

export interface CompCountdown {
  kg_remaining: number
  weeks_remaining: number
  required_kg_per_week: number | null
  actual_kg_per_week: number | null
  red_flag: boolean
}

export interface TodayPayload {
  date: string
  weekday_name: string
  readiness: Readiness
  sessions: Session[]
  structural_flags: StructuralFlags
  nutrition_focus: string
  trend_observation: string | null
  sleep: Sleep | null
  weight: Weight | null
  comp_countdown: CompCountdown | null
}
