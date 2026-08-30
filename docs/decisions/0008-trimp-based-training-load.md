# 8. Feed CTL/ATL/TSB/monotony/strain from TRIMP, not `activities.training_load`

Date: 2026-08-30
Status: Accepted
Supersedes: `metrics/load.py: build_daily_load_series()` as the input to
CTL/ATL/TSB, monotony/strain, and the Training page's sport-by-day chart, in
`api/training.py`, `coach/briefing.py`, `metrics/derived_daily.py`, and
`coach/weekly_retro.py`.

## Context

Francisco, looking at the rebuilt Training page: "but i actually want it to
be useful! Why can't you show the bikes, and once I start measuring my BJJ
sessions, the sessions as well?"

The honest answer traced to the input, not the chart: `activities.
training_load` (Garmin/Strava's own reported value) is NULL for essentially
every activity on this account except 9 old Strava runs (pre-June 2026) —
already documented extensively elsewhere in CLAUDE.md as a device-tier gap
(the Forerunner 165 doesn't report a `training_load` figure at all). No
amount of chart logic can plot a number that was never recorded.

But this project already has a real, working alternative: `metrics/
strain.py`'s Daily Strain ring already computes a genuine per-day load
estimate — Banister TRIMP (heart-rate-reserve method, 1991) wherever a real
`avg_hr` exists, Foster's method (RPE x duration) for BJJ manual logs not
already covered by a real matching activity. Checked directly against the
real database before deciding anything: bike rides (17 real rides, May-Aug
2026) have 100% `avg_hr` coverage; strength/weight-training sessions do too.
The data to make this useful already existed — it just wasn't being read.

## Decision

Replace every consumer of `activities.training_load`-based
`build_daily_load_series()` with `metrics.strain.build_activity_based_load_
series()` (new) — the same per-day TRIMP/Foster computation Daily Strain
already used for "today," extended to walk a full date range. One source of
truth for "how much did this day's training actually load the body," reused
by:
- The Daily Strain ring (unchanged, already existed)
- `api/training.py`'s CTL/ATL/TSB chart, monotony/strain, and (new)
  `build_load_by_sport_rows()` for the sport-by-day breakdown
- `coach/briefing.py`'s `tsb_persistently_negative` structural trigger
- `metrics/derived_daily.py`'s persisted CTL/ATL/TSB/monotony/strain/
  tsb_zscore history
- `coach/weekly_retro.py`'s weekly TSB/monotony summary

Deliberately did NOT stop at just fixing `api/training.py` (the page
Francisco was actually looking at) — `briefing.py`/`derived_daily.py`/
`weekly_retro.py` all independently built the same kind of series from the
same sparse column, and leaving them on the old source would have created a
FRESH inconsistency (the Training page showing rich real data while the
deload trigger and persisted history kept reading a near-empty one) — the
exact class of bug this whole investigation started by finding elsewhere
(see the dedup fixes below). Not migrated: `dashboard/views/training.py`
(the Streamlit fallback, frozen by prior decision, not kept in sync with
React-side changes) and `metrics/load.py: build_daily_load_series()` itself
(kept, unused by the migrated call sites, but not deleted — no reason to
remove a working, tested pure function).

## Two real bugs found and fixed en route (not part of the decision, but
## required before the migration could ship correctly)

1. **Cross-source dedup gap, `core/dedupe.py`**: 8 real Strava/Garmin ride
   pairs (the same physical rides, auto-uploaded from Garmin to Strava)
   never merged — start times differ by exactly 2 hours (Strava's raw CSV
   genuinely states local wall-clock time 2 hours off from Garmin's own
   `startTimeLocal`/`startTimeGMT` for the identical ride, confirmed against
   both the raw CSV and a live Garmin API call — not an ingestion bug on
   this project's side), and duration sometimes differs by far more than
   the existing 60s tolerance. `avg_hr` is identical (within 1bpm rounding)
   across every pair — a vanishingly unlikely coincidence for two genuinely
   different sessions — so a second matching tier now catches same-day,
   same-sport-family, near-exact-avg_hr pairs even when start/duration
   don't line up. Without this, switching to TRIMP would have DOUBLE-
   COUNTED every affected ride (both the Strava and Garmin copies
   independently contributing load) — found by that exact symptom
   (2026-08-15 showing 567 raw TRIMP, roughly double a normal ride).
2. **`_SPORT_FAMILIES` gap, same file**: `strength_training` (a real
   Garmin-reported sport label) had no family mapping at all, so a
   2026-08-24 Strava "weight_training" + Garmin "strength_training" pair
   for the identical gym session (avg_hr 116 on both) never even reached
   the matching logic. Added, along with `trail_running`/`treadmill_
   running` -> running and `lap_swimming` -> swimming, the same real gap
   pattern for labels not previously seen in this account's data.

## Consequences

- Real numbers change, visibly and correctly: the CTL/ATL/TSB chart now
  shows a genuine curve across the account's whole ~5-month Garmin-era
  history instead of a near-flat line that only reacted to 9 old runs and
  whatever BJJ got logged manually. Historical `derived_daily` recomputed
  (165 days) so the Trends/Training pages reflect this throughout, not just
  going forward.
- The old `is_stale`/`days_stale` staleness mechanism (`metrics/load.py:
  load_staleness()`) is now structurally dead for CTL/ATL/TSB/monotony/
  strain specifically — the new series always walks through to `as_of_date`,
  computing a real, confirmed value (including genuine 0.0 rest days) for
  every day, so "the series stopped updating N days ago" can no longer
  happen. Removed from `_load_based_metrics()`/`_tsb_zscore_metric()`
  rather than left in as dead code that looks like it still does something.
  The mechanism itself stays in place for weight/EWMA staleness, a genuinely
  different and still-real problem (a gap in weigh-ins).
- `config/athlete.yaml: training_load.bjj_rpe_calibration_factor` (still
  "uncalibrated," 1.0) is now bypassed for every migrated call site — BJJ's
  Foster load is scaled by `metrics/strain.py: STRAIN_FOSTER_SCALE` instead,
  the same constant Daily Strain already used. Two different calibration
  targets (this project's own training_load vs. TRIMP) shouldn't share one
  factor; kept deliberately separate, matching `strain.py`'s own existing
  reasoning for why that constant exists.
- TSB's absolute magnitude still has no validated "how much is too much"
  threshold (unchanged from ADR 0003/0007) — now backed by real data instead
  of a mostly-empty series, but the Training page's caveat under a large
  z-score was rewritten to say so plainly, replacing the now-inaccurate
  "likely a data-coverage artifact" framing from the page's first pass.

## Alternatives considered

- **Keep `activities.training_load`, just backfill it somehow.** Not
  possible — Garmin's API doesn't expose this figure on this hardware tier,
  confirmed repeatedly (Training Readiness has the identical gap). There is
  nothing to backfill from.
- **Calibrate BJJ's Foster load against `activities.training_load` as
  originally planned (kickoff doc 2.4).** Moot now — that column is being
  phased out as an input to these metrics entirely, so calibrating against
  it would be calibrating against a source no longer used.
- **Loosen the dedup match generally instead of adding a narrow secondary
  tier.** Rejected — this project's own precedent (the walking-activity
  under-merge case, documented earlier) explicitly favors under-merging
  over risking a false conflation; the secondary tier is narrow (same date,
  same sport family, near-exact avg_hr) specifically to avoid that risk.
