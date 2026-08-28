import type { ReadinessBand } from "@/types/today"

// Mirrors coach/rules.py: classify_readiness_band()'s 75/55 cutoffs exactly
// -- that function is the canonical single source of truth for these
// thresholds; this is a UI-only color mapping on top, same relationship
// dashboard/theme.py: band_color() already had to Python's own
// classify_readiness_band(). Only needed here for the sub-COMPONENT scores
// (hrv/rhr/sleep/tsb/subjective), since the backend already sends the
// overall score's own `band` directly in the payload.
export function scoreToBand(score: number | null): ReadinessBand {
  if (score === null) return "no_data"
  if (score >= 75) return "green"
  if (score >= 55) return "amber"
  return "red"
}

export const BAND_COLORS: Record<ReadinessBand, string> = {
  no_data: "var(--band-blue)",
  green: "var(--band-green)",
  amber: "var(--band-amber)",
  red: "var(--band-red)",
}

export const BAND_LABELS: Record<ReadinessBand, string> = {
  no_data: "No data",
  green: "Green",
  amber: "Amber",
  red: "Red",
}
