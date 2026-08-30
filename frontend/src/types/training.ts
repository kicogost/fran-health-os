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
  // Rebuilt 2026-08-30: means "is there enough daily_metrics.resting_hr
  // history to build a TRIMP-based load series at all" -- the real
  // prerequisite now, since the series always answers every day in range
  // (including genuine 0.0 rest days), not "did some activity happen to
  // have Garmin/Strava's own training_load value" like it used to.
  has_load_data: boolean
  ctl_atl_tsb: CtlAtlTsbPoint[]
  tsb_zscore: TsbZscore | null
  monotony_strain: MonotonyStrain | null
  load_by_sport: LoadBySportRow[]
  calisthenics: CalisthenicsRow[]
}
