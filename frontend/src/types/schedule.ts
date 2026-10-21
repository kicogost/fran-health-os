export type BlockKind =
  | "routine"
  | "mind"
  | "mobility"
  | "log"
  | "meal"
  | "coffee"
  | "training"
  | "work"
  | "rest"
  | "wind_down"
  | "sleep"

export interface ScheduleBlock {
  start: string
  end?: string
  kind: BlockKind
  title: string
  notes?: string
  /** Set on strength / sprint blocks: the prescribed session, shown when opened. */
  strength_session?: string
  sprint_session?: string
  exercises?: string[]
  workout_notes?: string
}

export interface ScheduleDay {
  day: string
  is_today: boolean
  eating_window: [string, string]
  blocks: ScheduleBlock[]
}

export interface SchedulePayload {
  today: string
  starts: string | null
  wake: string
  lights_out: string
  eating_window: [string, string]
  days: ScheduleDay[]
}
