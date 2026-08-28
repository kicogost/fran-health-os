# Health OS

Personal, local-first health data warehouse and coaching layer for Francisco — a single
BJJ competitor, not a generic fitness product. There is exactly one user. Optimise for
correctness, transparency, and readability six months from now. Do not optimise for
scale, generality, or configurability.

The original full spec this project was scaffolded from is
[`HEALTH_OS_KICKOFF.md`](HEALTH_OS_KICKOFF.md) — this file is the living, durable
rewrite of it. When the two disagree, this file wins (it reflects what actually got
built and any corrections made along the way); update this file, not the kickoff doc,
as the project evolves.

## Current status

**Phase 0, Phase 1, and Phase 2 all complete as of 2026-08-28.** Strava, Apple Health,
and now Garmin are all backfilled into the real `data/health.db` (565 activities, 431
days of `daily_metrics`) — Garmin's export arrived and was ingested the same day. This
is the milestone the whole project was blocked on: **real HRV data now exists**, current
through yesterday, which is what the readiness score (Phase 4) and the "how hard can I
push today" question have been waiting on since Phase 0.

**Phase 2 summary — Strava.** `ingest/strava_bulk.py` parses `activities.csv` from a
Strava data-export archive (per kickoff doc section 2.3, the per-activity `.fit.gz`/
`.gpx` files aren't touched — the CSV's own summary columns, including a `Training
Load` column, already cover everything `activities` needs). Two real-export gotchas
verified against Francisco's actual archive, not assumed:
- The header has 5 **duplicate column names** (Elapsed Time, Distance, Max Heart Rate,
  Relative Effort, Commute each appear twice, 103 columns total) — parsed by column
  index, not name, since a plain `csv.DictReader` would silently drop one of each pair.
- `Activity Date` carries **no timezone offset** at all (e.g. "Aug 22, 2026, 6:52:17
  AM"). Verified via each row's own sunrise/sunset epoch columns that this is
  Europe/Madrid local time — the implied local sunrise/sunset times land exactly right
  for Mallorca in that season. `core/timezones.py` gained `localize_to_utc()` for this
  exact case (local wall-clock time, no offset given).
- Result: 251 activities backfilled (matches the CSV's row count exactly).

**Phase 2 summary — Apple Health.** `ingest/apple_health.py` streams `export.xml`
(464MB real file; `lxml.etree.iterparse` handled 1.1M elements in ~5.5s) and
deliberately extracts only two things, not the whole export — see the module
docstring for the full reasoning:
1. **Workouts** → `activities`, source `apple_health`, filtered against
   `config/sources.yaml`'s `apple_health.exclude_source_names`/
   `exclude_source_name_substrings` (new file, per-source ingestion settings).
2. **Body mass** (`HKQuantityTypeIdentifierBodyMass`) → `daily_metrics.weight_kg`,
   restricted to an *allowlist* (`weight_source_names: [Renpho, RENPHO Health]`) rather
   than a denylist — weight is the one field where a wrong source is easy to get
   silently wrong. When a date has multiple readings, the latest wins — never averaged
   (design principle 6).

Steps/sleep/HR are deliberately **still not** ingested from Apple Health — now that
Garmin is loaded (below), it's the direct, richer source for all of these per the
kickoff doc's own precedence (design principle 5), so there's nothing to gain from
also pulling Apple Health's inferior duplicate copies. Apple Health's remaining
narrow role (watch-not-worn step gaps) is a real Phase 3 reconciliation task, not
done yet, but no longer blocked on "Garmin isn't loaded" — it's just not built.

Real findings from Francisco's actual 621MB export, not assumed:
- Multiple non-Francisco/duplicate sources are mixed into one export: Garmin syncs in
  as sourceName `"Connect"` (excluded), Strava as `"Strava"` (excluded, ingested
  directly instead), and a family member's watch as `"Apple Watch de roberta"`
  (excluded, confirmed with Francisco — not his data).
- `<Workout>` elements have no natural unique ID in this export version — `source_id`
  is synthesized via `ingest/common.py: synthetic_source_id()` from
  (source, start, end, type), so re-running the backfill stays idempotent.
- No reliable inline HR summary exists on real `<Workout>` elements (checked both
  BJJBuddy- and native-Watch-recorded workouts) — `avg_hr`/`max_hr` left `None` for
  Apple-Health-sourced activities rather than guessed at.
- **Real find: ~51 historical BJJ sessions already existed** — 39 via a "BJJBuddy" app
  (`workoutActivityType=MartialArts`) and 12 tagged "Wrestling" (closest built-in Apple
  category) via the Watch/Health app directly. Confirmed with Francisco: backfilled
  into `activities` (source=apple_health, sport=martial_arts/wrestling), **not**
  `bjj_sessions` — that table requires `session_rpe` (the manual-log schema), which
  this historical data doesn't have and shouldn't have invented for it.
- Result: 180 activities backfilled (301 total Workouts − 11 Connect − 110 Strava,
  exact match) + 112 days of weight. The weight parser found **78.45 kg on
  2026-08-21** — cross-validated against the figure Francisco gave directly in the
  comp-prep plan. Real end-to-end correctness signal, not just internal consistency.

**Phase 2 summary — Garmin (2026-08-28, the export arrived).** `ingest/garmin_bulk.py`
parses the GDPR-style "Export Your Data" archive — not a small health-specific export
like the other two, but a dump of literally every Garmin product line the account has
ever touched (aviation, golf, InReach, Navionics, Tacx...); health/fitness is one
folder among many, nested under a UUID-named directory that's different on every fresh
export (files are located via `rglob()`, not a fixed path, to handle that). Two things
extracted:
1. **Activities** (`DI-Connect-Fitness/*summarizedActivities.json`) → `activities`.
2. **Daily wellness**, merged from three separate JSON sources per calendar date:
   `DI-Connect-Aggregator/UDSFile_*.json` (steps, calories, resting HR, body battery,
   stress, respiration), `DI-Connect-Wellness/*_sleepData.json` (sleep stages + score
   — `calendarDate` here is *already* the wake-date, verified against real data, so
   Garmin does the design-principle-7 attribution for us), and
   `DI-Connect-Wellness/*_healthStatusData.json` — internally called "LHA" — which is
   **where HRV actually lives**, alongside Garmin's own baseline/status classification.

Real-export gotchas verified against Francisco's actual export, not assumed (full
detail in the module docstring):
- `distance`/`elevationGain`/`elevationLoss` on activities are in **centimeters**, not
  meters. Verified two ways: dividing by 100 turned three real runs into exactly
  5.02km/5.01km/3.01km (obviously-intentional round training distances); a real ride's
  elevation gain divided by 100 gave 630m, matching *exactly* what Strava recorded for
  what's almost certainly the same real ride. Dividing by 1000 instead (the first,
  wrong guess) gave an implausible 63m for hilly Mallorca terrain — worth remembering
  as a lesson: the first plausible-looking unit conversion isn't always right, cross-
  check against an independent number when one exists.
- No single Garmin "training load" scalar exists in this export — Garmin represents
  training stress via `aerobicTrainingEffect`/`anaerobicTrainingEffect` (0-5 each),
  which map directly to `activities.aerobic_te`/`anaerobic_te`. `training_load` stays
  NULL for Garmin rows.
- `training_readiness` (Garmin's own composite) is **not present anywhere in this bulk
  export** — confirmed by search, not assumed absent. Only available live via the
  unofficial API (Phase 6). Stays NULL until then.
- HR zones come as 7 Garmin buckets (`hrTimeInZone_0`..`_6`) against our 5-zone schema
  — folded conservatively (zone 0 into zone 1, zone 6 into zone 5) rather than dropped.
- Result: 139 activities, 384 of 431 `daily_metrics` days now have real Garmin data —
  **142 days of real HRV, 160 days of resting HR, 138 days of sleep stages**, current
  through 2026-08-27 (yesterday). Not stale like the Strava training-load gap noted
  above — this is live, current data.

**Dedup note, checked not assumed**: adding Garmin's 139 historical activities (back to
2018) did *not* trigger any new merges beyond the 5 already found between Strava/Apple
Health — checked this wasn't a silent matching failure by inspecting actual time gaps:
167 activities share a local date with a Garmin activity, and the closest candidate had
a 31-second start-time match but an 8-minute duration mismatch (two devices' auto-
detection algorithms drawing different boundaries around what might be the same walk).
The conservative 120s/60s matching correctly declines to merge that — better to under-
merge than incorrectly conflate two auto-detected walks that might be genuinely
different. Known limitation, mostly affecting passive walking (not a training modality
this project's readiness/load work actually cares about) — not "fixed" by loosening
thresholds, since that risks the opposite, worse failure mode.

All three backfills are idempotent (verified: re-running produced identical row
counts, including after adding Garmin) and logged to `ingest_runs`. Entry point:
`uv run python scripts/backfill.py [--source strava|apple_health|garmin|all]`.

**Next up**: with real HRV/RHR/sleep finally live, the HRV baseline, RHR baseline,
sleep debt, and readiness score (Phase 4, previously all blocked) can actually be
built now — not done yet as of this entry, flagged for the next session.

**Next session: check whether Garmin's export has arrived** under
`data/raw/garmin/bulk_export/`. `scripts/backfill.py --source garmin` already detects
its presence/absence and says so clearly. Once it exists, inspect its real structure
the same way Strava/Apple Health's were inspected — do not assume from public docs —
before writing `ingest/garmin_bulk.py`. That's the last piece of Phase 2.

**While waiting on Garmin (2026-08-27), two things got built out of strict phase
order** — both deliberately chosen because neither depends on Garmin data or Phase 3
dedup, so there was no rework risk:

1. **Manual BJJ logger** (`scripts/log_bjj.py`, kickoff doc 2.4) — the first-class,
   not-an-afterthought ingestion path for the one training stimulus no export
   captures. Flag-driven (`--type class --duration 90 --rpe 7 ...`) or fully
   interactive (run with no flags). Upserts on `(date, session_type)`, warns before
   overwriting an existing session. `computed_load` (Foster's method) is computed
   automatically by `core.models.BjjSession`, never entered by hand. Added a
   `training_load.bjj_rpe_calibration_factor` placeholder (1.0, marked
   "uncalibrated") to `config/athlete.yaml` — real calibration against Garmin's own
   `training_load` waits for Garmin data, per kickoff doc 2.4.
2. **Weight trend / comp countdown preview** (`metrics/body_comp.py` +
   `scripts/weight_report.py`) — a deliberately partial slice of Phase 4, pulled
   forward because weight has no Garmin dependency to reconcile (Apple Health/Renpho
   is the sole source). Pure, hand-verified functions: `compute_weight_ewma()` (7-day
   EWMA, recursive form), `weight_trend_ols()` (21-day trailing OLS slope + 95% CI,
   `confidence="insufficient_data"` below 3 real points in the window — never a false
   CI), `comp_countdown()` (kg/weeks remaining, required vs. actual kg/week, red flag
   above 0.7 kg/week). Nothing here writes to `derived_daily` yet — that's part of
   doing the full Phase 4 metric suite together, not this early slice.

   **Real output against Francisco's actual data** (2026-08-27): 112 days of weight,
   2021-06-17 to 2026-08-21 (sparse historically, picking up cadence in 2026 — not a
   data artifact, checked). Latest weigh-in 78.45 kg; 7-day EWMA 79.37 kg. 21-day
   trend: **+0.552 kg/week, 95% CI [-1.507, +0.404]** (n=6) — the interval straddles
   zero, meaning the trend isn't statistically distinguishable from flat or even
   losing yet. This is the system doing exactly what it's supposed to (kickoff doc
   section 6: "the noise is comparable to the signal at these magnitudes") — not a
   bug, and it'll tighten up fast now that Block 1 of the comp-prep camp has daily
   logging going. Comp countdown: 52 days / 7.4 weeks to 2026-10-18, 2.37 kg to lose,
   required 0.319 kg/week — under the 0.7 red line, currently "on track" (though the
   "actual" rate is unreliable this early per the CI above).

**Still while waiting on Garmin (2026-08-27, continued) — two more pieces, both
verified against real data first, not spec-guessed:**

3. **Cross-source activity dedup** (`core/dedupe.py`, a real slice of Phase 3) — built
   after *confirming* (not assuming) Francisco's actual database had genuine
   duplicates: 5 activities existed in both `strava` and `apple_health` with identical
   start times and near-identical durations (Strava's generic "workout" label vs.
   Apple's "functional_strength_training" — same real sessions). `dedupe_activities()`
   implements the full design-principle-5 matching rule (start within 120s, duration
   within 60s, compatible sport family via a small mapping table) and precedence
   (Garmin > Strava > Apple Health, configurable), even though only 2 of the 3 sources
   are loaded yet — adding Garmin later needs zero changes here, its rows will just
   out-rank on the same precedence list. Deletes the loser row(s), records them in the
   winner's `merged_from` JSON (that JSON *is* the audit trail — no separate table).
   Now wired into `scripts/backfill.py` as the automatic last step after every
   ingestion run, not a separate command to remember.

   **Real bug found and fixed the same session**: re-running the backfill re-ingests
   a source and resurrects an already-merged-away row (expected/by design — the next
   dedupe pass just re-merges it), but the first implementation appended to
   `merged_from` without deduplicating, so the same (source, source_id) pair piled up
   duplicate entries on every re-run. Fixed with `_dedupe_merged_from()`; regression
   test added (`test_reingested_loser_does_not_duplicate_merged_from_entry`). Real
   result against the actual DB: 5 duplicate groups merged, 426 activities remain
   (down from 431), stable and idempotent across repeated `scripts/backfill.py` runs
   — verified by running it twice in a row.
4. **Waist measurement logger** (`scripts/log_measurement.py`) — same shape as
   `log_bjj.py` (flag-driven or interactive, upserts on `(date, measurement_type)`,
   warns before overwriting). `body_measurements` was sitting empty; the comp-prep
   plan calls for a weekly Sunday measurement, so this is immediately usable.

## Proprietary training-load / readiness build-out (2026-08-27)

Francisco asked directly: since HRV needs to wait for real Garmin data, can the
system build its own training-load and readiness signals from what's already
available (Strava, Apple Health, BJJ/wellness logs) plus whatever he logs himself —
researched first, not invented. Findings (sources in the chat, worth re-reading
before touching this area again):

- **ACWR (what the kickoff doc originally specced for this) has real, documented
  problems** — Impellizzeri et al. and multiple systematic reviews found "severe
  mathematical coupling" and inconsistent injury association. Built first, then
  **dropped entirely** once Francisco weighed in on the caveat — see ADR
  [0003](docs/decisions/0003-drop-acwr-for-ctl-atl-tsb.md) for the full reasoning.
  It is **not** in this codebase.
- **CTL/ATL/TSB (Banister impulse-response model — TrainingPeaks' "Performance
  Manager Chart" math) is the sole training-load-ratio signal**, per ADR 0003.
  Exponentially-weighted fitness (42-day time constant) minus fatigue (7-day) =
  freshness.
- **Session-RPE (already in `bjj_sessions`) is specifically validated for BJJ**,
  not just borrowed from other sports — a 2020 study on BJJ athletes found it
  correlated with creatine kinase (muscle damage) and reduced sleep quality.
- **The single highest-value addition, and the one needing zero new hardware, is
  a structured daily wellness questionnaire** — the Hooper-Mackinnon protocol
  (sleep quality, stress, fatigue, muscle soreness, each 1-10). Subjective ratings
  like this are validated to correlate with recovery/performance at least as well
  as objective measures, and it's the one signal that works today, independent of
  Garmin entirely.
- **RPE/RIR-anchored autoregulation** (RPE 8 ~ 2 reps in reserve, RPE 9 ~ 1, RPE
  10 ~ failure) is the validated way to make "Amber: hold load" concrete for the
  calisthenics sessions — not built yet, noted for when the coaching layer
  (Phase 7) lands.

**Built as a result (migration 0002, `core/migrations/0002_bjj_wellness_and_load.sql`)**:

- **`bjj_sessions`**: the boolean `gassed` is replaced with `rounds_gassed` (a
  count, strictly more informative — "gassed=true" doesn't say if that was 1
  round of 8 or 6) and a new `session_feeling` column, CHECK-constrained to
  `dizzy < gassed < tired < okay` (worst to best) — these are Francisco's own
  three BJJ-specific tracking questions, alongside the existing `rounds_rolled`.
  `dizzy` is deliberately treated as a genuine safety signal, not just "very
  tired" — `log_bjj.py` prints a note when it's logged. `rounds_rolled`/
  `rounds_gassed`/`session_feeling` are only asked for `class`/`open_mat` — never
  for `gi_drilling` (technique-only, nothing to roll).
- **`subjective_log`**: four new 1-10 fields (`sleep_quality`, `stress`,
  `fatigue`, `muscle_soreness`) — all the SAME polarity (1=best, 10=worst) so
  they sum cleanly into `hooper_index` (4=excellent, 40=terrible), computed
  automatically by `core.models.SubjectiveLogEntry` only when all four are
  present (a partial sum would misrepresent the day). New
  `scripts/log_wellness.py` covers the *entire* `subjective_log` row (this
  table never had a dedicated logger before) — every field optional, flag mode
  if any content flag is passed, interactive prompts otherwise.
- **`metrics/load.py`** (new): `build_daily_load_series()` combines
  `activities.training_load` with BJJ `computed_load` (scaled by the
  still-uncalibrated `bjj_rpe_calibration_factor`) into one total per calendar
  day — walking every day and filling rest days with **0.0, a real value**,
  unlike weight's "missing = unknown." `compute_monotony_strain()` (Foster) and
  `compute_ctl_atl()` (Banister/TrainingPeaks) build on that series — no ACWR
  function (ADR 0003). 15 tests, several hand-computed exactly.

**Important real finding, worth remembering before trusting these numbers**:
ran the load metrics against the actual database (2026-08-27) and the result is
*stale*, not current — `activities.training_load` is populated for only 9 of
251 real Strava activities, **all of them runs**, and only in a March-June 2026
window. Every other sport (rides, weight training, walks — i.e. everything
Francisco has actually done since June, including the current comp-prep block)
has zero `training_load` coverage in the Strava export. Combined with no BJJ
sessions logged yet (table's still empty — that's on Francisco to start using
`log_bjj.py`), the daily load series currently ends 2026-06-13, ~2.5 months
stale. The machinery is correct and tested; **the current live inputs just
don't cover recent training yet.** **Update, 2026-08-28: Garmin landing did
NOT fix this** — checked, Garmin's bulk export has no `training_load` scalar
either (see `metrics/load.py`'s docstring and the Garmin summary above). This
will fix itself once BJJ/wellness logging accumulates and once a calibration
target (probably `aerobic_te`/`anaerobic_te`, not `training_load`) gets
decided — until then, don't read today's CTL/ATL/TSB as if they describe
today. The Hooper wellness index doesn't have this problem (it's whatever
Francisco logs that day), which is part of why it's the highest-value piece of
this build-out.

## Readiness score: HRV/RHR baselines, sleep debt, composite (2026-08-28)

Unblocked by the Garmin backfill above. Built exactly to kickoff doc section 6's
spec — no scope changes, unlike the ACWR->TSB swap.

- **`metrics/baselines.py`**: `compute_hrv_baseline()` — 60-day rolling median +
  population SD, `insufficient_data` below 21 days, then a **seed phase** (21-59
  days) using Francisco's own placeholder thresholds (>90ms balanced, 75-85ms
  capped — the doc didn't specify the 85-90ms and <75ms gaps, so those are
  documented interpretation choices, easy to correct), then **switches to the
  computed baseline automatically at 60 days** — the switchover is visible in
  the returned `baseline_method` field itself (`"seed"` -> `"computed"`), not a
  separate log statement. `compute_rhr_baseline()` — same structure, plus
  `sustained_rise_flag` for 3 consecutive days each >1 SD above their *own*
  trailing baseline (the window slides day to day, not one shared window).
  `compute_sleep_debt()` — rolling 14-*calendar*-day sum of (8h need - actual),
  hours, positive = deficit.
- **`metrics/load.py`** gained `compute_tsb_zscore()` — scores the latest TSB
  against its own trailing 90-day distribution (z-score), not a borrowed
  absolute threshold, since raw TSB magnitude depends on still-uncalibrated
  load units (same reasoning as the ACWR removal, ADR 0003).
- **`metrics/readiness.py`**: `compute_readiness_score()` — the 0-100 composite,
  weights from `config/athlete.yaml: readiness_score` (35% HRV / 25% sleep / 15%
  RHR / 15% TSB / 10% subjective `hooper_index`, all tunable). Sleep blends last
  night's duration and the 14-day debt 50/50 (the doc didn't specify a split).
  RHR and TSB score in the SAME direction as HRV (higher = more ready) except
  RHR, which is inverted (elevated RHR = less ready) — each documented in its
  own scoring helper. **Missing components are never invented as a neutral 50**
  — they're dropped and the remaining weights renormalize to sum to 1.0;
  `coverage` reports what fraction of the full weight was real data, so a
  score built from 2 of 5 components is visibly less trustworthy than one from
  all 5, not silently identical.

31 tests across the three modules, several with an exact closed-form derivation
(not approximation): for a window of (n-1) identical values plus one outlier as
the latest point, both the median-based baseline deviation and the mean-based
z-score reduce to clean constants (`n/sqrt(n-1)` and `sqrt(n-1)` respectively)
independent of the outlier's magnitude — derived independently in the test
files, not copied from the implementation, so they actually catch transcription
bugs (sign errors, wrong window, wrong which-value-is-latest).

**Real output against the actual database (2026-08-28)**: HRV baseline
`status="low"` — yesterday's 80ms sits just past -1 SD below the 60-day median
of 90.5ms (SD~10.3ms), genuinely at the edge, not deep. RHR baseline
`status="balanced"`, exactly at its own median (very stable — no
`sustained_rise_flag`). Sleep debt is *negative* (a ~1.9h surplus over the last
10 real nights — `confidence="partial"`, since only 10 of the trailing 14
calendar days have real sleep data). TSB z-score is -1.45, but **this is
computed from the same stale, pre-June load series flagged above** — read it as
demonstrating the machinery works, not as a description of today's actual
freshness. `hooper_index` is `None` — Francisco hasn't logged wellness data yet.
Overall composite: **47.0, confidence="partial" (coverage 0.90 — only the
subjective component missing)**. Per the kickoff doc's own bands this would
read "Red," but **that reading shouldn't be trusted yet** given the TSB
component's stale input — worth re-running once BJJ/wellness logging has
accumulated and a load-calibration decision is made. The three genuinely live
components (HRV, RHR, sleep) are trustworthy today; TSB and subjective are not,
for two different reasons (stale data; no data at all).

**Not yet done**: none of this writes to `derived_daily` yet (same partial-slice
pattern as `body_comp.py` — lands with the full Phase 4 metric suite). No CLI/
dashboard surfaces these numbers yet; they're only reachable by calling the
functions directly, as done above.

**Phase 1 summary** (2026-08-27): `core/migrations/0001_initial_schema.sql` is the
source of truth for the schema (all 7 tables from the target schema below, applied via
`core/db.py: apply_migrations()`, tracked in a `schema_migrations` table);
`core/schema.sql` is a human-readable snapshot kept in sync by a drift-guard test
(`tests/core/test_schema_sync.py`). `core/db.py` provides `init_db()` (connect + apply
pending migrations), a generic `upsert()` (idempotent, natural-key-based, JSON-encodes
`dict`/`list` values automatically — used for `daily_metrics.sources`,
`activities.merged_from`, `derived_daily.inputs_json`), and `start_ingest_run()` /
`finish_ingest_run()` for the audit table. `core/models.py` has a dataclass per table
with `to_row()`/`from_row()`; `to_row()` omits `None` fields by default specifically so
partial upserts from different sources (e.g. Garmin fills `resting_hr`, Apple
Health/Renpho fills `weight_kg`, same date, separate ingestion runs) don't clobber each
other — covered by `tests/core/test_db.py::TestUpsert::test_partial_upsert_does_not_clobber_other_columns`.
Environment note: this machine had no `uv` and only system Python 3.9 (project needs
3.12+) — installed `uv` via Homebrew, which then installed Python 3.12.14 itself
(`uv python install 3.12`); `uv sync` + `uv run pytest`/`uv run ruff` work normally from
here on.

**2026-08-27 update — comp-prep plan received.** Francisco sent a full 8-week block
plan for the Oct 18 2026 comp, saved verbatim at
[`docs/comp_prep_2026-10-18.md`](docs/comp_prep_2026-10-18.md) and structured into
`config/athlete.yaml` under `comp_prep` (active 2026-08-24 → 2026-10-18, supersedes
`weekly_architecture` for the duration — see that file for the full block-by-block
detail, taper-week schedule, and strength session exercises). Comp date is now
confirmed: **2026-10-18**. Two things came up in the same message that are still open:

### Resolved from the same message (both confirmed by Francisco, 2026-08-27)

- **Division weight limit: 77.0 kg.** Confirmed over the 77.27 kg figure in the
  original kickoff doc — `config/athlete.yaml: goals.primary.weight_division_kg` is now
  `77.0`. Use this for the comp-countdown red-line math once Phase 4 lands.
- **Dashboard hosting: staying local-only.** No Vercel, no hosted dashboard. Phase 5
  proceeds exactly as originally specced — `streamlit run` on Francisco's machine,
  accessed there or via Tailscale/VPN when away. Design principle 1 (local-first, no
  cloud services) stands unchanged. If remote access ever comes up again, Tailscale/VPN
  to the local Streamlit instance is the answer, not a hosted rearchitect.

- **Renpho scale → dashboard, automatically.** Francisco weighs in daily via the
  Renpho Health app. The natural path is: Renpho writes to Apple Health (confirm this
  toggle is on in the Renpho app) → our existing Apple Health ingestion (already planned
  for Phase 2/6) picks it up, filtered by source device. This needs one addition to the
  dedup design: for the `weight_kg` field specifically, Apple-Health-via-Renpho should
  be treated as authoritative (Garmin has no scale on this hardware, so there's no
  higher-precedence source to defer to for body weight — the general Garmin > Strava >
  Apple Health precedence in design principle 5 is about *activities*, not body weight).
  No new adapter needed if the HealthKit toggle is confirmed on; falls back to an
  unofficial Renpho API only if it turns out Renpho doesn't sync to HealthKit at all.
  Record this as an ADR once Phase 2/6 actually implements it.
- **"Minimise manual input, everything flows in automatically."** Noted as a standing
  preference. Applies cleanly to weight (via Renpho/Apple Health) and to Garmin/Strava
  activities. Does **not** apply to BJJ session logging or the weekly self-check signals
  (subjective energy, niggles) — those aren't captured by any sensor Francisco owns, so
  they stay manual until/unless the Cirqa (ADR 0001) or another device changes that.
  Don't quietly drop the manual BJJ logger in the name of automation; flag it if asked.
- **Weekly self-check heuristic.** The comp-prep plan adds Francisco's own simplified
  tracking rule: bodyweight 2-3x/week, waking RHR, subjective energy 1-10 per mat
  session, and niggles — if 2 of those 4 signals go red in the same week, add an extra
  rest day. Captured in `config/athlete.yaml: comp_prep.weekly_self_check`. This is a
  second, simpler heuristic alongside the Phase 4/7 computed readiness score and
  structural triggers, not a replacement for them — both should be checkable in the
  rules engine when Phase 7 lands.
- **No water cut, ever, at this weight gap.** Added as a hard nutrition guardrail
  (`config/athlete.yaml: nutrition.water_cut_allowed: false`) alongside the existing
  never-fast / never-extreme-deficit rails.

**2026-08-27, continued — chest strap purchase confirmed, recording workflow settled.**
Francisco is buying a Garmin chest strap (per ADR 0002 above) rather than the Cirqa.
Practical recording workflow (pairing, watch on/off, Cardio vs HIIT profile, and the
Bluetooth-range gap risk of taking the watch off mid-roll) is written up in
[`docs/bjj_recording_workflow.md`](docs/bjj_recording_workflow.md) — read that before
Phase 6 (live Garmin sync) or before advising on any BJJ-recording question. It also
records a schema design decision for later phases: the chest-strap-recorded Garmin
activity and the manual `bjj_sessions` log entry for the same class should be **linked**
by `activity_id` (matched date/time), not deduplicated against each other — they're two
views of one session, not two copies of it. This changes how `bjj_sessions` and the
calibration factor (kickoff doc 2.4) get built in Phases 1 and 3; nothing to act on yet.

Build phases, in order — **stop at the end of each and show the result before
continuing; do not run ahead**:

0. ✅ Repo scaffold, `pyproject.toml`, `.env.example`, `config/athlete.yaml`, this file, ADR 0001.
1. ✅ Schema + DB layer (`core/db.py`, `core/schema.sql`, upsert helpers, `ingest_runs` audit table).
2. ✅ Historical backfill — Strava, Apple Health, and Garmin all backfilled.
3. ⬜ Deduplication and canonical merge across sources.
4. ⬜ Derived metrics (section "Derived metrics" below), with unit tests.
5. ⬜ Dashboard (Streamlit), read-only first, then logging forms.
6. ⬜ Live incremental sync (Garmin unofficial client + Strava API) + `scripts/sync.py`.
7. ⬜ Coaching rules engine + briefing generator.
8. ⬜ Scheduling (launchd/cron) + correlation analysis.

## Athlete profile

| Field | Value |
|---|---|
| Name | Francisco |
| Age | 24 |
| Height | 176 cm |
| Weight | 78.45 kg as of 2026-08-21 (had plateaued 79-79.8 kg since mid-July 2026) |
| Location | Portals Nous, Mallorca |
| Timezone | Europe/Madrid (DST-aware) |
| Units | Metric throughout |
| Week starts | Monday |

All of the above, plus goals, weekly architecture, nutrition guardrails, equipment, and
injury guardrails, live as structured data in **`config/athlete.yaml`** — read from
there, don't hardcode these values in code.

**Goals:** no-gi BJJ comp, **Sunday 2026-10-18**, **-77.0 kg** division (confirmed
2026-08-27, supersedes the 77.27 kg figure from the original brief), weight at/under
limit on comp morning with performance intact. Secondary: visible muscle definition,
better mat conditioning.

**Weekly architecture — currently the 8-week comp-prep block plan** (active
2026-08-24 → 2026-10-18; see `config/athlete.yaml: comp_prep` and
[`docs/comp_prep_2026-10-18.md`](docs/comp_prep_2026-10-18.md) for full detail): Mon
BJJ (technical) + Strength A; Tue BJJ hard rounds; Wed BJJ (technical) + Strength B; Thu
off; Fri open mat / competition rounds; Sat Z2 bike with his father; Sun off. Volume
comes down and intensity goes up across 4 blocks (base → build → sharpen → taper), with
a fully custom taper-week schedule for the final week before competing. The coaching
layer advises *within* this shape, same as before — it still never redesigns it or adds
a 4th/5th hard session.

The **pre-comp steady-state architecture** (daily pre-breakfast mobility, gi drilling
Tue evening, calisthenics Tue/Thu mornings, etc.) is preserved in
`config/athlete.yaml: weekly_architecture` (currently `active: false`) as what training
reverts to after 2026-10-18, pending confirmation from Francisco post-comp.

**Nutrition guardrails (hard):** 180 g protein/day is the one hard number; ~2,300 kcal
target (~500 kcal deficit); no alcohol; 2 black coffees/day; Saturday restaurant dinner
is planned-for, not a violation. Known constraint: **social meals are the primary
deficit disruptor** — deficit compliance, not programming, is the binding constraint on
comp weight. Never recommend calorie obsession, fasting, extreme deficits, or
"make-up" tactics for a social meal.

**Injury guardrails (hard, encode in rules, not just prose):** never recommend running
(prior right knee injury — permanent). Never recommend increasing load on pressing/
overhead work in any week where a neck niggle was logged (recurring neck vulnerability
under forward-head load).

**Equipment:** pull-up bar (terrace), 12 kg kettlebell, 10 kg barbell + 50 kg plates,
adjustable bench.

## Data sources — the actual constraints

Most of this project's difficulty lives here, not in the analysis. Full detail in
kickoff doc section 2; summary:

- **Garmin (primary source of truth)** — sleep stages, overnight HRV, RHR, Body
  Battery, stress, VO2max, training load/readiness, activities, steps. No official free
  personal API exists. Live sync goes through the **unofficial** `garminconnect` +
  `garth` client, wrapped behind one adapter module so a Garmin login-flow breakage is a
  one-file fix. MFA needs an interactive first auth; `garth` caches session tokens to
  disk after that. **Historical backfill uses the official bulk export** (Account
  Management Center → "Export Your Data" → zip of JSON/FIT, takes days to generate) —
  do not scrape years of history through the unofficial client. Verify the real zip
  folder structure against Francisco's actual export before assuming a layout. Evaluate
  `garmindb` as a reference/dependency in Phase 2 and record the call in an ADR. FIT
  files parsed with `fitdecode`/`fitparse`.
- **Apple Health** — mostly a **duplicate** of Garmin (Garmin Connect syncs into it), so
  it is not an independent source. It earns its place only for (1) step/movement data
  from times the watch wasn't worn, and (2) third-party HealthKit apps that don't write
  to Garmin. One-time export via the Health app → `export.zip` → huge `export.xml`,
  parsed with **streaming** `lxml.etree.iterparse` (never `ElementTree.parse`, it will
  exhaust RAM). Ongoing sync via the **Health Auto Export** iOS app, folder-drop first,
  REST later if wanted. Every record carries a source device — filter out
  Garmin-originated records at ingest.
- **Strava** — official free API, `stravalib` for OAuth/refresh. Look up current
  published rate limits rather than trusting a stale number; implement backoff against
  them. Recent activities duplicate Garmin (which auto-uploads to Strava) — Strava's
  real value is **historical depth** predating the Forerunner 165. Backfill via Strava's
  bulk archive export, not by paging the API across years.
- **BJJ (the tracking gap)** — currently the single largest untracked training
  stimulus (~270-400 min/week). First-class manual logger (CLI + dashboard form):
  `date, session_type (class|open_mat|gi_drilling), duration_min, rounds_rolled,
  session_rpe (1-10), gassed (bool), niggles (free text), notes`. Load via Foster's
  method: `load = duration_min × session_rpe`, calibration factor against Garmin's
  training load (on days both exist) stored explicitly in config, not hardcoded.

**Hardware decision (ADR [0002](docs/decisions/0002-bjj-wearable-chest-strap.md),
supersedes [0001](docs/decisions/0001-bjj-wearable.md)):** a Garmin chest strap **with
onboard memory** — **HRM 600** (current flagship, ~$170, machine-washable detachable
pod, rechargeable) is the pick, **HRM-Pro Plus** (~$130, fixed hand-wash-only pod,
~12mo coin-cell battery) a valid cheaper alternative — worn under the rashguard/gi, not
the Cirqa and not Fitbit. 0001 picked the Cirqa (bicep-worn, screenless) over Fitbit;
once accuracy was named as the explicit priority, the answer changed to a chest strap —
ECG beats any optical sensor (wrist *or* bicep) regardless of placement, since PPG is
inherently vulnerable to motion/compression artifact and ECG isn't. **Onboard memory is
not optional** — checked 2026-08-27: the entry-level HRM 200/HRM-Dual straps have *no*
onboard storage and only broadcast live, so taking the watch off mid-roll (the intended
recording workflow, see `docs/bjj_recording_workflow.md`) would just lose data on those
models rather than buffering through the gap. Still lands in Garmin Connect with zero
new ingestion pipeline, fully hidden under a rashguard, and removes the wrist/bicep
snag risk entirely rather than just reducing it. **Don't buy until Phase 3 is running
and the BJJ data gap is provably the bottleneck** — unchanged from 0001, only the device
pick changed. **Francisco confirmed 2026-08-27 he ordered the Garmin HRM 600**
specifically (not the HRM-Pro Plus alternative) — that's the model
`docs/bjj_recording_workflow.md` should assume once it's in hand.

## Design principles (non-negotiable)

1. **Local-first.** Runs on Francisco's machine only. No cloud services, no hosted DB, no
   telemetry. Outbound traffic only to Garmin, Strava, and package registries.
2. **Raw data is immutable.** Downloads land in `data/raw/` and are never edited/deleted
   by code. All transforms are reproducible from raw.
3. **One canonical store.** `data/health.db` (SQLite). Every query, chart, and coaching
   decision reads from it — no parallel CSVs of record.
4. **Idempotent ingestion.** Re-running any sync produces the same DB state. Upsert on
   natural keys, never blind insert.
5. **Explicit deduplication.** Every activity carries `source` + `source_id`. Precedence:
   Garmin > Strava > Apple Health. Match on start time within 120s, duration within 60s,
   same sport family. Every merge decision logged to an auditable table.
6. **Never invent data.** No silent interpolation, no gap-filling with averages. Missing
   = `NULL`, and visibly missing on the dashboard. Derived values from partial inputs
   carry a `confidence`/`n_days` column.
7. **Timezone-aware everywhere.** UTC in the DB, Europe/Madrid on render. Sleep sessions
   spanning midnight attribute to the wake date.
8. **Secrets in `.env` only**, never committed. `.env.example` is the template. A
   pre-commit hook should block credential-shaped strings in commits.
9. **Every derived number is traceable.** Any dashboard number must be explainable down
   to its inputs and arithmetic via one click-through or one command. No black boxes.

## Repo layout

```
config/
  athlete.yaml        profile, goals, training architecture, nutrition, equipment, injuries
  sources.yaml        per-source ingest settings (Apple Health exclude/weight-allow lists)
data/
  raw/                 immutable per-source downloads (gitignored)
  health.db             the one canonical store (gitignored)
src/health_os/
  ingest/               strava_bulk.py, apple_health.py, garmin_bulk.py, common.py (shared helpers) — bjj_manual.py not needed (log_bjj.py writes directly)
  core/                 db.py, timezones.py, dedupe.py (activities cross-source dedup, live), schema.sql (snapshot, v2), migrations/000{1,2}_*.sql (source of truth), models.py
  metrics/              body_comp.py (weight trend + comp countdown), load.py (monotony/strain, CTL/ATL/TSB — no ACWR, ADR 0003), baselines.py (HRV/RHR baselines, sleep debt), readiness.py (0-100 composite) — none of these write to derived_daily yet
  coach/                rules.py, briefing.py, weekly_retro.py
  dashboard/             app.py (Streamlit)
scripts/                backfill.py (Phase 2 entrypoint, runs dedupe.py automatically after ingestion), log_bjj.py (manual BJJ logger), log_wellness.py (daily Hooper-Mackinnon wellness), log_measurement.py (waist/tape logger), weight_report.py (Phase 4 preview) — sync.py not yet written
tests/                  core/, ingest/, metrics/, scripts/, fixtures/ (synthetic — never real personal data, fixtures are committed to git)
docs/decisions/          ADRs, one per non-obvious choice
```

## Canonical schema (target — lands in Phase 1)

Minimum tables, full column lists in kickoff doc section 5:

- **`daily_metrics`** — one row/date: weight, RHR, HRV, sleep stages/score, Body
  Battery, stress, steps, kcal, VO2max, training readiness, respiration, SpO2, skin temp.
- **`activities`** — one row/session: `source`/`source_id`, timing, sport, HR zones,
  training load, TE, power, `merged_from` (JSON of superseded rows).
- **`bjj_sessions`** — the manual log, joined into `activities` with computed load.
  Also `rounds_rolled`/`rounds_gassed`/`session_feeling` (dizzy/gassed/tired/okay,
  worst-best — migration 0002, Francisco's own three BJJ tracking questions). Once
  the chest strap (ADR 0002) is in use, also carries a `linked_activity_id` pointing at
  the matching Garmin-recorded activity for that session — linked, not deduplicated
  against it; see `docs/bjj_recording_workflow.md`.
- **`subjective_log`** — one row/date: felt note, protein_hit, gassed, niggles, day_note,
  `social_meal` (correlated against weight trend — this is the known deficit disruptor),
  plus a Hooper-Mackinnon-inspired `sleep_quality`/`stress`/`fatigue`/`muscle_soreness`
  (1-10 each) summing into `hooper_index` (migration 0002).
- **`body_measurements`** — waist_cm (Sunday, fasted, below navel; baseline 86 cm) + other tape measures.
- **`derived_daily`** — every computed metric below, with the input values and window
  sizes that produced it.
- **`ingest_runs`** — audit log: source, timestamps, rows in/upserted/skipped, errors.

## Derived metrics (Phase 4, pure functions, unit-tested against fixtures)

- **HRV baseline** ✅ (`metrics/baselines.py: compute_hrv_baseline()`) — 60-day rolling
  median + SD. `balanced` within ±1 SD, `low`/`high` beyond. Needs ≥21 days before any
  status; below that, `insufficient_data`. Seed thresholds while the window fills (>90
  ms balanced, 75-85 ms capped) are a temporary placeholder — switches to the computed
  baseline automatically at 60 days, visible via the returned `baseline_method` field
  rather than a separate log statement.
- **RHR baseline** ✅ (`compute_rhr_baseline()`) — same structure. Flags a >1 SD
  sustained rise across 3 consecutive days via `sustained_rise_flag`.
- **CTL/ATL/TSB (Banister/TrainingPeaks)** ✅ (`metrics/load.py: compute_ctl_atl()`) —
  replaces the kickoff doc's original ACWR spec (ADR 0003: the sports-science
  literature has moved against ACWR — mathematical coupling, inconsistent injury
  association). CTL = fitness (42-day-time-constant EWMA of daily load), ATL = fatigue
  (7-day), TSB = CTL−ATL = freshness. Must include BJJ manual load or the numbers are
  meaningless — currently mostly doesn't (see the load-staleness note above).
- **Monotony/strain (Foster)** ✅ (`compute_monotony_strain()`) — monotony = mean daily
  load ÷ SD of daily load over 7 days; strain = weekly load × monotony. Flags
  monotony >2.0.
- **Sleep debt** ✅ (`metrics/baselines.py: compute_sleep_debt()`) — rolling 14-calendar-
  day sum of (8.0h need − actual), reported in hours.
- **Weight trend** ✅ (`metrics/body_comp.py`) — never show raw daily weight as
  headline. 7-day EWMA + OLS slope over trailing 21 days (kg/week) with its confidence
  interval — noise is comparable to signal at these magnitudes.
- **Comp countdown** ✅ (`metrics/body_comp.py`) — EWMA weight, kg remaining, weeks
  remaining, required kg/week vs actual kg/week. Required >0.7 kg/week = red (a
  performance-risk problem, not a fat-loss problem).
- **Readiness score (0-100)** ✅ (`metrics/readiness.py: compute_readiness_score()`) —
  own composite alongside Garmin's Training Readiness, so disagreement is visible.
  Weights live in `config/athlete.yaml: readiness_score` (tunable): 35% HRV deviation
  (SD units, clamped ±2), 25% sleep (last-night vs 8h need + 14-day debt), 15% RHR
  deviation (inverted), 15% TSB scored self-relatively (a z-score within the athlete's
  own trailing TSB distribution — raw TSB magnitude depends on load units that aren't
  universally comparable, so no borrowed absolute threshold), 10% subjective input
  (`hooper_index`). Missing components are dropped and remaining weights renormalized
  (never invented as neutral) — `coverage` reports how much of the full weight was
  real. Component breakdown always included. Real output against the actual database,
  2026-08-28: **47.0, confidence "partial"** — see the readiness build-out section
  above for the full component-by-component read and its caveats (TSB stale, no
  subjective data logged yet).

## Coaching layer (target — lands in Phase 7)

**Deterministic rules first, prose second.** The rules engine produces a decision + reasons; the language layer only narrates that — it never invents a recommendation the rules didn't produce.

**Daily briefing** (morning): (1) today's session adjusted for readiness, (2) one
nutrition focus, (3) one trend observation *only if actually notable* — silence is valid,
don't manufacture an insight daily.

**Readiness bands** (against the fixed weekly shape):
- **Green ≥75** — train as scheduled; BJJ live rounds fine; lifting days get a load progression attempt.
- **Amber 55-74** — train as scheduled, cap intensity; BJJ technical/no-ego rolls; hold calisthenics load; bike strictly Z2.
- **Red <55** — downgrade, don't delete: BJJ → drilling only; calisthenics → mobility + light kettlebell. Never prescribe a full rest day off one bad number — require 2 consecutive red days or 3 amber days first.
- **Structural triggers** — 3 consecutive days HRV < baseline−1SD, or TSB persistently
  very negative (deep accumulated fatigue without recovery, threshold TBD once real
  load-unit calibration exists) for 4+ days, or monotony >2.0 with strain in the
  last-8-weeks top quartile → formal capped-week/deload recommendation. Deloads are
  already ~every 4 weeks on the calendar — flag when calendar and data disagree.

**Hard safety rails (in the rules engine, not just prose):** never recommend running;
never increase pressing/overhead load in a week with a logged neck niggle; never a
deficit deeper than 2,300 kcal implies, never fasting, never "making up" for a social
meal; never add a 4th/5th hard session — the architecture is fixed.

**Weekly retro** (Sunday): 7-day weight trend + CI, sessions completed vs planned, total
load with TSB/monotony, sleep totals, protein adherence rate, social-meal count
correlated against weight trend, waist delta, proposed calisthenics progression.

**Correlation engine** (last, needs 90 days of data): Spearman rho with n and p between
candidate inputs (sleep, deep sleep, social meals, steps, BJJ load, gi/no-gi) and
outcomes (next-day HRV/readiness, weekly weight slope, gassed rate). n<30 = provisional.
Never present correlation as causal. Top 3 findings max.

## Dashboard (target — lands in Phase 5)

Streamlit, Plotly, dark theme, raw points always shown behind smoothed lines (lighter
shade). Pages: **Today** (readiness + breakdown, prescription, sleep, weight EWMA, comp
countdown) · **Trends** (weight/HRV/RHR/sleep stages, 30/90/365-day windows) ·
**Training** (load by day/sport, CTL/ATL/TSB chart, monotony, calisthenics progression) ·
**Comp prep** (weight trajectory vs required line, projected finish + uncertainty) ·
**Log** (BJJ/subjective/waist forms) · **Data health** (freshness, missing days, dedupe
log, last ingest run — not optional, it's how pipeline breakage gets noticed).

## Working agreement

- Python 3.12+, `uv` for deps, `ruff` for lint/format, `pytest` for tests, type hints on
  every public function.
- **Ask before adding any dependency** not already named in this doc or `pyproject.toml`, and say what it buys.
- Small commits, conventional commit messages, one logical change each.
- Tests mandatory on ingest + metrics layers. Dashboard can go untested.
- Any non-obvious choice gets a numbered ADR in `docs/decisions/` with alternatives considered.
- If something here is wrong, out of date, or a bad idea — say so before building it.
- When a real API/library behaves differently than documented here, trust the API and
  update this file.

## Definition of done for v1

One command each morning: syncs Garmin + Strava, recomputes everything, prints a
briefing (readiness + components, today's prescribed session, one nutrition focus, any
notable trend). Dashboard is one command away. BJJ gap closed by manual logging until
hardware closes it properly. Every number traceable to its inputs.

## Out of scope

Multi-user support, authentication, hosting/deployment, mobile app, Docker (unless a
dependency forces it), LLM calls inside the metrics layer (derived numbers must be
deterministic/reproducible — language generation happens only in the briefing layer,
from rules-engine output).
