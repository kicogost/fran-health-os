// Mirrors src/health_os/api/log.py's health-history request models and the
// rows its GET /api/health-history/* endpoints return (core/models.py's
// to_row(include_none=True) shape -- every field always present, nullable
// ones as `null`, never absent).

export interface BloodworkRequest {
  date: string
  test_name: string
  value: number
  unit?: string | null
  reference_range_low?: number | null
  reference_range_high?: number | null
  notes?: string | null
}

export interface BloodworkRow {
  id: number
  date: string
  test_name: string
  value: number
  unit: string | null
  reference_range_low: number | null
  reference_range_high: number | null
  notes: string | null
}

export type MedicalEventCategory = "condition" | "injury" | "surgery" | "hospitalization" | "other"
export type MedicalEventStatus = "ongoing" | "resolved" | "unknown"

export interface MedicalEventRequest {
  date: string
  category: MedicalEventCategory
  title: string
  status: MedicalEventStatus
  resolved_date?: string | null
  notes?: string | null
}

export interface MedicalEventRow {
  id: number
  date: string
  category: MedicalEventCategory
  title: string
  status: MedicalEventStatus
  resolved_date: string | null
  notes: string | null
}

export type MedicationType = "medication" | "supplement"

export interface MedicationRequest {
  name: string
  type: MedicationType
  start_date: string
  dosage?: string | null
  frequency?: string | null
  end_date?: string | null
  notes?: string | null
}

export interface MedicationRow {
  id: number
  name: string
  type: MedicationType
  dosage: string | null
  frequency: string | null
  start_date: string
  end_date: string | null
  notes: string | null
}

export type AllergySeverity = "mild" | "moderate" | "severe"

export interface AllergyRequest {
  allergen: string
  reaction?: string | null
  severity?: AllergySeverity | null
  date_identified?: string | null
  notes?: string | null
}

export interface AllergyRow {
  allergen: string
  reaction: string | null
  severity: AllergySeverity | null
  date_identified: string | null
  notes: string | null
}

export interface FamilyHistoryRequest {
  relation: string
  condition: string
  notes?: string | null
}

export interface FamilyHistoryRow {
  relation: string
  condition: string
  notes: string | null
}
