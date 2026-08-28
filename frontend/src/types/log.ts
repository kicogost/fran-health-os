// Mirrors src/health_os/api/log.py's request models exactly.

export interface BjjSessionRequest {
  date: string
  session_type: "class" | "open_mat" | "gi_drilling"
  duration_min: number
  session_rpe: number
  rounds_rolled?: number | null
  rounds_gassed?: number | null
  session_feeling?: "dizzy" | "gassed" | "tired" | "okay" | null
  niggles?: string | null
  notes?: string | null
}

export interface WellnessRequest {
  date: string
  felt_note?: string | null
  protein_hit?: boolean | null
  gassed?: boolean | null
  niggles?: string | null
  day_note?: string | null
  social_meal?: boolean | null
  sleep_quality?: number | null
  stress?: number | null
  fatigue?: number | null
  muscle_soreness?: number | null
}

export interface WaistRequest {
  date: string
  value_cm: number
  notes?: string | null
}

export interface ExerciseEntry {
  exercise: string
  sets: number
  reps?: number | null
  added_weight_kg?: number | null
  notes?: string | null
}

export interface CalisthenicsRequest {
  date: string
  session_type: "strength_a" | "strength_b"
  session_rpe?: number | null
  exercises?: ExerciseEntry[] | null
  notes?: string | null
}
