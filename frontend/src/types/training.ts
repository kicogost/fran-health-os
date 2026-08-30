// Mirrors src/health_os/api/training.py's exact shape.

export interface CtlAtlTsbPoint {
  date: string
  ctl: number
  atl: number
  tsb: number
}

export interface MonotonyStrain {
  monotony: number | null
  strain: number | null
  weekly_load: number | null
  n_days: number
  confidence: string
  flag_high_monotony?: boolean
}

export interface TsbZscore {
  z_score: number | null
  n_days: number
  confidence: string
}

export interface LoadBySportRow {
  date: string
  sport: string
  load: number
}

export interface CalisthenicsExercise {
  exercise: string
  sets: number
  reps: number | null
  added_weight_kg: number | null
  notes: string | null
}

export interface CalisthenicsRow {
  date: string
  session_type: string
  session_rpe: number | null
  exercises: CalisthenicsExercise[]
}

export interface TrainingPayload {
  has_load_data: boolean
  // True when the load series' last real date is 3+ days before today --
  // added 2026-08-30 because has_load_data alone is all-or-nothing (one
  // real BJJ log flips it true even while training_load coverage is still
  // months stale for everything else). See CLAUDE.md's training-load
  // build-out notes for why this is a real, current data-coverage gap.
  is_stale: boolean
  days_stale: number
  ctl_atl_tsb: CtlAtlTsbPoint[]
  tsb_zscore: TsbZscore | null
  monotony_strain: MonotonyStrain | null
  load_by_sport: LoadBySportRow[]
  calisthenics: CalisthenicsRow[]
}
