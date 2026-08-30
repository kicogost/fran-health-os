// Mirrors src/health_os/api/today.py: build_today_payload()'s exact shape.
// Keep these two in sync by hand -- no codegen in this project (deliberately
// small, personal-scale; not worth an OpenAPI-codegen pipeline for one page).

export type ReadinessBand = "no_data" | "red" | "amber" | "green"

export interface ReadinessComponent {
  raw: number | Record<string, number | null>
  score: number
  weight_used: number
  // The actual sensor reading (e.g. "90ms", "52bpm", "7h29m") -- never the
  // same number as `score`, which is the abstracted 0-100 readiness
  // contribution, not a raw value. `null` when no raw display makes sense
  // for this component (TSB/subjective) or the underlying reading is
  // missing. Added 2026-08-30 after a real mix-up: the rings only ever
  // showed `score`, and it was reasonable to read "HRV 47" as 47ms.
  display_raw: string | null
  // True when weight_used is 0 (e.g. config/athlete.yaml: weight_tsb
  // temporarily 0.0 while its inputs are known unreliable) -- present in
  // `components` for transparency, but contributing nothing to the total,
  // so it must look visibly different from a real, counted low score.
  excluded: boolean
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
