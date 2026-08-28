// Mirrors src/health_os/api/data_health.py's exact shape.

export interface FreshnessField {
  field: string
  label: string
  status: string
  last_date: string | null
  days_stale?: number
}

export interface DedupeEntry {
  activity_id: string
  source: string
  local_date: string
  sport: string | null
  merged_from: { source: string; source_id: string }[]
}

export interface IngestRun {
  id: number
  source: string
  started_at: string
  finished_at: string | null
  status: string
  rows_in: number | null
  rows_upserted: number | null
  rows_skipped: number | null
  errors: string[] | null
}

export interface DataHealthPayload {
  freshness: FreshnessField[]
  missing_days: string[]
  missing_days_window: number
  dedupe_log: DedupeEntry[]
  ingest_runs: IngestRun[]
}
