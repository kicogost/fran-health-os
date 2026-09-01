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
  // for this component (subjective) or the underlying reading is missing.
  // Added 2026-08-30 after a real mix-up: the rings only ever showed
  // `score`, and it was reasonable to read "HRV 47" as 47ms.
  display_raw: string | null
  // True when weight_used is 0 -- a general mechanism, present in
  // `components` for transparency, but contributing nothing to the total,
  // so it must look visibly different from a real, counted low score.
  // (Originally motivated by TSB being temporarily zero-weighted; TSB was
  // removed from this composite entirely by ADR 0007 and never appears in
  // `components` anymore, but the mechanism stays for any future case.)
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
  duration_min?: number
  distance_km_range?: [number, number]
  zone_range?: string
  label: string
  instruction: string
}

export interface StrainComponent {
  source: string
  method: "trimp" | "foster_estimated"
  raw_load: number
  description: string
}

// A genuine INTENSITY read (not another accumulated-load number) computed
// only from a BJJ activity's `likely_sparring`-classified laps
// (metrics/bjj_laps.py: compute_sparring_intensity(), added 2026-08-31,
// corrected same day). Standard Karvonen %HRR, duration-weighted across
// the sparring laps, banded into standard Karvonen/Zoladz zones (1-5;
// `zone: 0`/`zone_label: "minimal"` for a rare sub-50%-HRR reading). Shown
// ALONGSIDE the whole-session Strain below, on a DIFFERENT scale entirely
// -- never compare `pct_hrr`/`zone` directly against `Strain.strain`/
// `Strain.zone`. `null` when not available (a rest day, a non-BJJ day, a
// BJJ day with no laps, no sparring-classified laps, or missing resting/
// max HR that day) -- never invented (design principle 6).
//
// A first version of this field (`SparringStrain`, since removed) put a
// second Strain number here on the SAME 0-21 accumulated-load scale as
// `Strain` below -- that was the wrong kind of metric for "how hard were
// the rounds" (see metrics/bjj_laps.py's module docstring for the full
// account) and is not what this shape represents.
export interface SparringIntensity {
  pct_hrr: number
  zone: number
  zone_label: string
  avg_hr: number
  sparring_duration_min: number
}

export interface Strain {
  strain: number | null
  zone: "light" | "moderate" | "high" | "all_out" | null
  components: StrainComponent[]
  total_raw_load: number | null
  sparring_intensity: SparringIntensity | null
}

export interface StructuralFlags {
  downgrade_to_rest: boolean
  hrv_sustained_low: boolean
  tsb_persistently_negative: boolean
  monotony_strain: boolean
}

// Calendar-anchored to the competition date -- distinct from Deload below,
// which is fatigue-triggered. See coach/rules.py: taper_status().
export interface Taper {
  days_to_competition: number
  active: boolean
}

// Fatigue-triggered, autoregulated -- never calendar-triggered (research,
// 2026-08-30: a scheduled non-fatigue-triggered deload showed no benefit in
// the one RCT that tested it). See coach/rules.py: should_deload().
export interface Deload {
  recommended: boolean
  markers_fired: string[]
  markers_required: number
  duration_days: number
  volume_reduction_pct: number
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
  strain: Strain
  readiness: Readiness
  sessions: Session[]
  structural_flags: StructuralFlags
  taper: Taper
  deload: Deload
  nutrition_focus: string
  trend_observation: string | null
  sleep: Sleep | null
  weight: Weight | null
  comp_countdown: CompCountdown | null
}
