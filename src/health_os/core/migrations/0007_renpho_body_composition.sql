-- Migration 0007: full body-composition detail from Renpho's own CSV export.
--
-- Francisco's RENPHO Health app can export a CSV directly
-- (`data/raw/renpho/*.csv`) with every field the scale's bioimpedance
-- measurement produces, not just the two (lean mass, BMI) that happened to
-- ride along in Apple Health's "Body Mass" bundle (migration 0005). Real
-- header, confirmed by direct inspection of Francisco's actual export, not
-- assumed:
--   Date, Time, Weight(kg), BMI, Body Fat(%), Skeletal Muscle(%),
--   Fat-Free Mass(kg), Subcutaneous Fat(%), Visceral Fat, Body Water(%),
--   Muscle Mass(kg), Bone Mass(kg), Protein (%), BMR(kcal), Metabolic Age,
--   Optimal Weight(kg), Target to optimal weight(kg), Target to optimal fat
--   mass(kg), Target to optimal muscle mass(kg), Body Type, Remarks
--
-- `Weight(kg)` and `BMI` map onto the existing `weight_kg`/`bmi` columns
-- (migration 0005) -- no new columns needed for those two.
--
-- `Fat-Free Mass(kg)` is NOT a new column -- cross-checked directly against
-- 4 real overlapping dates already in `daily_metrics.lean_body_mass_kg`
-- (populated via the Apple-Health/Health-Auto-Export path): 2026-08-28
-- (59.60 both), 2026-08-29 (59.50 both), 2026-08-30 (59.64 both), 2026-08-31
-- (59.78 both) -- exact matches every time. "Fat-Free Mass" and "Lean Body
-- Mass" are standard synonyms for the same body-composition quantity, and
-- this real cross-check confirms it's genuinely the same number here too, so
-- this CSV's Fat-Free Mass column is ingested straight into the existing
-- `lean_body_mass_kg` column rather than a new, redundant one.
--
-- Every other body-composition field here has no existing column, so seven
-- new nullable REAL columns and two new nullable INTEGER columns are added.
-- `visceral_fat_rating` is named deliberately unlike the others: the raw
-- values (7-10 in Francisco's real export) are a small unitless Renpho
-- rating, not a percentage, so it isn't suffixed `_pct` like its neighbors.
--
-- The `Optimal Weight(kg)` / `Target to optimal ...` / `Body Type` /
-- `Remarks` columns are deliberately NOT ingested -- confirmed by direct
-- inspection that every single row in Francisco's real export has `--` in
-- all of them, so there is nothing real to store; a genuine checked-empty
-- gap, not a silent omission.
ALTER TABLE daily_metrics ADD COLUMN body_fat_pct REAL;
ALTER TABLE daily_metrics ADD COLUMN skeletal_muscle_pct REAL;
ALTER TABLE daily_metrics ADD COLUMN subcutaneous_fat_pct REAL;
ALTER TABLE daily_metrics ADD COLUMN visceral_fat_rating INTEGER;
ALTER TABLE daily_metrics ADD COLUMN body_water_pct REAL;
ALTER TABLE daily_metrics ADD COLUMN muscle_mass_kg REAL;
ALTER TABLE daily_metrics ADD COLUMN bone_mass_kg REAL;
ALTER TABLE daily_metrics ADD COLUMN protein_pct REAL;
ALTER TABLE daily_metrics ADD COLUMN bmr_kcal INTEGER;
ALTER TABLE daily_metrics ADD COLUMN metabolic_age INTEGER;
