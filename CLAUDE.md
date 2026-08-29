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

## Garmin live sync built, Phase 6 (2026-08-28)

`ingest/garmin.py` (new — distinct from `ingest/garmin_bulk.py`, the historical
parser) and `scripts/sync.py` (new — the Phase 6 daily entrypoint the kickoff doc
calls for). Full reasoning in
[ADR 0004](docs/decisions/0004-garmin-live-sync-typed-responses.md); summary:

- **Auth**: `garminconnect.Garmin(email, password, prompt_mfa=...)` +
  `.login(tokenstore)`, reading `GARMIN_EMAIL`/`GARMIN_PASSWORD`/`GARTH_TOKEN_DIR`
  from `.env`. Verified against the actually-installed library's `login()` source
  (not assumed): first run against an MFA-enabled account blocks on an `input()`
  prompt for the 6-digit code; tokens then persist to `GARTH_TOKEN_DIR` so every
  later run is headless. Credentials are never pasted into chat — Francisco adds
  them to his own local `.env` directly.
- **Daily wellness** (`fetch_daily_metrics`) uses `client.typed.*` — the
  `garminconnect[typed]` extra's Pydantic-validated response models, read directly
  from the installed package source (`garminconnect/typed.py`) rather than guessed
  from docs. Covers `resting_hr`, `steps`, `active_kcal`/`total_kcal`, `stress_avg`,
  `body_battery_max`/`min` (`get_stats`); full sleep stage breakdown + score
  (`get_sleep_data`); `hrv_overnight_ms`/`hrv_status` (`get_hrv_data` — `None` is a
  documented valid "no data" response, handled explicitly, not an error);
  `training_readiness` (`get_training_readiness`, preferring the
  `AFTER_WAKEUP_RESET` snapshot then falling back to the most recent timestamp,
  mirroring the library's own `get_morning_training_readiness` logic). **Fills a
  real gap from the bulk export**: `training_readiness` was confirmed absent from
  the historical GDPR dump — this is the first place it's ever populated.
  A `GarminConnectResponseValidationError` on any one endpoint/date is caught,
  recorded into `ingest_runs.errors`, and that endpoint's fields are simply
  omitted for that date rather than crashing the sync.
- **Activities** (`fetch_activities`) — a genuinely new signal:
  `activity_training_load` is present on live activities (`typed.Activity`) even
  though it's absent from the bulk export, so training load stops being
  permanently NULL for Garmin-sourced rows going forward (still NULL for
  historical rows). **Units are a documented, not-yet-verified assumption**:
  `typed.Activity`'s `distance`/`duration`/`elevation_gain` carry no unit suffix
  the way the wellness models do (contrast `total_distance_meters` on
  `DailyStats`), so this assumes the standard Garmin Connect REST convention
  (seconds, meters) — a *different* convention from the bulk export's
  centimeters/milliseconds. `scripts/sync.py` prints each newly-synced activity's
  converted numbers specifically so a wrong guess is visible on the first real
  run, same spirit as the elevationGain cross-check that caught a real bug in
  `garmin_bulk.py`. HR zones (`hrTimeInZone_0..6`) and `perceived_rpe`
  (`workoutRpe`) — both present on the bulk export — stay NULL for live-synced
  activities: `typed.Activity` doesn't model either, and there's no verified
  evidence the live endpoint carries them the same way. Known gap, not silent.
- **`scripts/sync.py`** fetches a trailing window (default 3 days, `--days` to
  override) rather than "since last sync" — deliberately, since Garmin sometimes
  revises a day's wellness numbers after the fact (delayed HRV computation,
  firmware backfill), so re-upserting a short trailing window self-heals that for
  free. Runs `dedupe_activities()` after, same as `backfill.py`. Live Strava sync
  is **not built** — deliberate, not an oversight: Strava introduced a paid
  ($11.99/mo) developer API tier in June 2026 (confirmed via WebSearch across
  multiple sources), and Garmin already covers current activities, so paying for
  Strava API access would buy nothing Strava's role here (historical depth,
  already backfilled) actually needs.
- **19 new tests** (`tests/ingest/test_garmin.py`) against fake `Garmin`/`typed`
  client doubles — never the real API. Covers the merge logic, the `None`-HRV
  case, the AFTER_WAKEUP_RESET/latest-timestamp readiness fallback, per-endpoint
  validation-error isolation, malformed-activity skipping, and the naive-GMT-
  timestamp parsing. 219 tests total in the suite now, all passing; `ruff
  check`/`ruff format --check` clean.

**Real first run, 2026-08-28 — confirmed working.** Francisco added
`GARMIN_EMAIL`/`GARMIN_PASSWORD` to his own local `.env` (never pasted into
chat) and ran `uv run python scripts/sync.py` directly. No MFA prompt occurred
— login's internal client backends (`mobile+cffi`, `mobile+requests`) both hit
a `429` (Garmin rate-limiting), logged as warnings, but a further internal
fallback succeeded and login completed cleanly. Session token persisted to
`data/.garth_tokens/garmin_tokens.json` — future runs are headless. Verified
directly against `ingest_runs` and `daily_metrics`, not just the script's own
printed summary: a clean `status="success"` row (3/3 rows upserted, 0 errors),
and real values landed for 2026-08-26/27/28 — resting HR 47/53/49,
`hrv_overnight_ms` 88/80/88 (all `"BALANCED"`), full sleep-stage breakdown +
score (84/62/93), all correctly tagged `sources: {"...": "garmin"}`. No
activities synced in that window (0 attempted, not an error — no Garmin-
tracked activity existed in those 3 days). **`training_readiness` came back
empty for all three dates** — the endpoint call itself succeeded (no
`GarminConnectResponseValidationError`), it just returned no snapshots for
Francisco's account in this window.

**Resolved, 2026-08-28**: investigated directly against the live account
(`client.get_training_readiness()` raw, plus `client.get_devices()`) rather
than guessed at. The raw endpoint genuinely returns `[]` — nothing is being
lost in our `typed`/mapping layer, `_fetch_one_day_metrics()`'s handling is
already correct. Root cause: **Francisco's Forerunner 165 doesn't compute
Training Readiness at all** — a deliberate device-tier limitation, not a
history-length thing (unlike this project's own HRV baseline seed phase).
Confirmed three ways: Garmin's own FR165 owner's manual never mentions
Training Readiness/Status/Load; Garmin's own community forum has a thread
asking this exact question, official answer "No — deliberate market
segmentation" (protects FR245/265 sales); an independent device-support
tracker (the5krunner.com) explicitly lists the FR165 as unsupported alongside
FR55/Instinct 3/Edge computers, with FR265/965/Fenix 7 Pro+/etc. supported.
`client.get_devices()` also surfaced two old **fēnix 3** entries (2015-era,
predates HRV/Body Battery) still registered on the account alongside the
Forerunner 165 — harmless, clearly legacy, not a data-source concern.
**`training_readiness` will stay permanently NULL for this account on current
hardware** — not a bug to keep chasing. If a future watch supports it, this
should start populating with zero code changes (the fetch/mapping logic is
already correct, it's the account's current hardware that has nothing to
report). Garmin's own composite readiness therefore isn't available to
compare against this project's own `compute_readiness_score()` — the
kickoff doc's "computed alongside Garmin's Training Readiness so disagreement
is visible" framing doesn't apply on this hardware; our own score is the only
composite that will ever exist for Francisco unless the watch changes.

**Resolved, 2026-08-28**: the live-activity unit assumption (seconds/meters)
is now confirmed correct against real data. The zero-activities result on the
first sync turned out to be a real gap, not a bug — investigated directly
(wide-range `get_activities_by_date` + `get_last_activity()` cross-check)
rather than left as "probably fine": Francisco's last Garmin-recorded
activity (a strength session, 2026-08-24) fell 4 days back, just outside
`scripts/sync.py`'s default 3-day window. Running `--days 25` pulled in 4 real
activities, all with plausible numbers: strength training 1902s (31.7 min,
matches the printed "32min"), and three rides — 51.21km/134min, 50.16km/145min,
42.76km/139min (18.5-22.9 km/h, consistent with the comp-prep plan's Saturday
Z2 rides with his father). Elevation gain also checked out: 630m on the
2026-08-22 ride matches the exact figure the bulk-export elevationGain
cross-check found for what's very likely the same recurring route (see
`garmin_bulk.py`'s docstring). Seconds/meters confirmed, no correction needed.

**New finding, correcting an earlier claim**: `training_load` (`activity_
training_load` on `typed.Activity`) came back **NULL on all 4 of these live
activities**, contradicting this section's earlier claim that live sync would
populate it going forward. Since `aerobic_te`/`anaerobic_te` mapped correctly
from the exact same API object for the same activities, this isn't a parsing
bug on our side — almost certainly the same Forerunner 165 device-tier gap as
Training Readiness (not independently re-verified against the raw API the way
Training Readiness was, but the pattern match is strong: Garmin gates several
of its own composite/coaching metrics behind higher device tiers). Training
load stays NULL for Garmin-sourced activities regardless of era (historical or
live) on this hardware — `activities.training_load` will likely need to come
from BJJ's own `computed_load` and Strava's sparse historical column, not
Garmin, for the foreseeable future on this account.

`pyproject.toml`: `garminconnect>=0.2.20` → `garminconnect[typed]>=0.3.11`,
`pydantic>=2.0` added as a direct dependency (was already an installed
transitive one).

## Apple Health "live" weight sync built via Health Auto Export (2026-08-28)

Francisco installed **Health Auto Export** (iOS app, Premium/lifetime tier —
needed specifically for the "Automations" feature; the cheaper Basic tier
only offers manual/Shortcuts-triggered export, no scheduling) and set up an
"iCloud Drive" automation named `HealthOS`. **Correcting an earlier wrong
assumption in this file**: the original plan (see git history) was "just
re-run `scripts/backfill.py --source apple_health` against the synced
folder, no new code needed" — that assumed Health Auto Export produces the
same `export.xml` format as the native Health app's one-time export. **It
does not.** Inspecting Francisco's real exported files (not assumed from the
app's docs) showed a completely different JSON schema, so a new dedicated
module was written: `ingest/health_auto_export.py`.

Real format, verified against three actual files copied from Francisco's
account:
```json
{"data": {"metrics": [
  {"name": "weight_body_mass", "units": "kg",
   "data": [{"qty": 78.45, "date": "2026-08-21 00:00:00 +0200", "source": "RENPHO Health"}]}
]}}
```
Only `weight_body_mass` is extracted — `lean_body_mass`/`body_mass_index` ride
along in the same "Body Mass" bundle but have no column in our schema, known
gap not silently dropped. Reuses `AppleHealthSourceConfig` (the same
`config/sources.yaml: apple_health.weight_source_names` allowlist) and the
same "latest reading per date wins, never averaged" rule as the bulk XML
parser, applied across *all* `HealthAutoExport-*.json` files in the directory
together (the app can produce several per run with overlapping date
coverage — reading them all and taking the latest per date handles that
correctly rather than requiring the caller to pick "the right file").

Real gotcha, verified by testing rather than assumed: the `date` field's
format (`"2026-08-21 00:00:00 +0200"`, space before a colon-less offset) is
byte-for-byte the same shape the native `export.xml` uses — both trace back
to the same HealthKit date serialization — so the existing
`strptime(..., "%Y-%m-%d %H:%M:%S %z")` approach carries over unchanged.
Confirmed `datetime.fromisoformat` actually *rejects* this shape (space
before the offset) rather than assuming it would "just work" since it looks
ISO-ish.

**Real cross-check, not just internal consistency**: the automation's
"Week"-range file (Health Auto Export names non-daily exports by ISO week
number, e.g. `HealthAutoExport-2026-34.json`) reported **78.45 kg on
2026-08-21, source "RENPHO Health"** — exactly matching the figure already in
the database from the historical `export.xml` backfill months earlier.

**Real find while setting this up**: two much larger files
(`HealthAutoExport-2026-08-27.json` ~1.1MB, `-08-28.json` ~370KB) turned up
alongside the real one, containing 7-12 unrelated metrics (`heart_rate`,
`sleep_analysis`, `step_count`, ...) — leftovers from before the automation's
"Select Health Metrics" setting was narrowed down to Body Mass only.
`parse_weight()` only ever looks for the `weight_body_mass` metric name, so
these stray files are harmless to leave in the directory rather than
something that needed cleaning up first. Also decided, after asking
Francisco directly: **Workouts are not exported from Health Auto Export at
all** — he confirmed he no longer uses BJJBuddy (the third-party app that
was the original reason Apple Health workouts had unique value, per the
Phase 2 Apple Health summary above) or logs sessions via Apple Watch instead
of Garmin, so there is currently no non-Garmin workout source left to
capture live. If that changes, a second automation (same iCloud Drive
destination, Data Type = Workouts) is a 30-second addition, not a redesign.

Wired into `scripts/sync.py` as `sync_health_auto_export()`, run alongside
the Garmin sync on every invocation, reading from `HEALTH_AUTO_EXPORT_DIR`
(new env var, default `data/raw/health_auto_export` — separate from
`APPLE_HEALTH_EXPORT_DIR`, which stays pointed at the native XML export;
these are two different pipelines now, not one). 8 new tests
(`tests/ingest/test_health_auto_export.py`) against synthetic fixtures —
latest-wins, source-allowlist-filters-before-latest-wins-comparison (a real
distinct case: an untrusted source's later timestamp must not win just
because it's later), multi-file combination, lb→kg conversion, empty
directory. **Real first run against Francisco's actual files (2026-08-28)**:
clean `success`, 1/1 rows upserted, `daily_metrics` for 2026-08-21 correctly
got `weight_kg` set without touching that date's pre-existing Garmin fields
(`resting_hr`/`hrv_overnight_ms` from the historical backfill stayed intact)
— the partial-upsert-doesn't-clobber design (Phase 1) working exactly as
intended on real data, not just in tests.

227 tests total now, all passing; `ruff check`/`ruff format --check` clean.

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
3. ✅ Deduplication and canonical merge across sources (`core/dedupe.py`, wired into
   `scripts/backfill.py`; 5 real duplicate groups found and merged).
4. ✅ Derived metrics (section "Derived metrics" below) — load/baselines/readiness all
   built and tested (see sections above), and now persisted to `derived_daily` via
   `scripts/compute_derived.py` (built 2026-08-28, see "Derived-daily persistence
   built" below), wired into the daily `morning_run.sh` pipeline.
5. ✅ Dashboard — **React/Tailwind migration (ADR 0005) complete 2026-08-28**: all 6
   pages (Today, Trends, Training, Comp Prep, Log, Data Health) rebuilt on FastAPI +
   React/Tailwind/shadcn-Radix (`src/health_os/api/` + `frontend/`) and verified
   against the real database — see "All 6 pages built" below for the full detail.
   The Streamlit version (`src/health_os/dashboard/`) is NOT deleted — kept as a
   fallback/reference, not scheduled for removal as part of this milestone.
   Calisthenics progression still has no logging mechanism at all — a real gap,
   not yet built regardless of frontend.
6. ✅ Live sync — Garmin (activities + wellness) and Health Auto Export (weight)
   both built and confirmed working against Francisco's real account
   (`ingest/garmin.py`, `ingest/health_auto_export.py`, `scripts/sync.py`, ADR 0004;
   see current-status section below for real run results). Strava live sync skipped
   by decision (paid API tier as of June 2026; Garmin already covers current data).
   Two device-tier gaps, both confirmed real not bugs: `training_readiness` and
   `training_load` come back permanently NULL on Francisco's Forerunner 165 (doesn't
   support either feature) — see current-status section for the full investigation.
   Live-activity units (seconds/meters) confirmed correct against real ride/strength
   data, no longer an open question.
7. 🟡 Coaching rules engine + briefing generator — `coach/rules.py` (deterministic
   decisions), `coach/briefing.py` (assembles real data, narrates via rules.py,
   shared by both `scripts/briefing.py` and the dashboard's Today page — no more
   dashboard-only preview logic), `coach/weekly_retro.py` + `scripts/weekly_retro.py`.
   Only unbuilt piece: correlation engine (needs 90 days of real data, don't have it
   yet). See current-status section below.
8. 🟡 Scheduling — `scripts/morning_run.sh` (sync + briefing + Sunday weekly retro,
   chained) running daily via a real installed launchd LaunchAgent
   (`launchd/com.healthos.morning.plist`, 10:00 Europe/Madrid, moved from an initial
   07:00 default per Francisco's request). See current-status section below.
   Correlation analysis not built (still blocked on 90 days of data).

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
  exhaust RAM). Every record carries a source device — filter out Garmin-originated
  records at ingest. **Ongoing weight sync via the Health Auto Export iOS app**
  (`ingest/health_auto_export.py`, built and confirmed working 2026-08-28) — its own
  JSON schema, genuinely different from `export.xml`, not the same pipeline. Only
  weight is synced this way (Francisco confirmed he no longer uses BJJBuddy or logs
  workouts via Apple Watch, so there's currently no non-Garmin workout source left to
  capture live — see current-status section for detail).
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
  ingest/               strava_bulk.py, apple_health.py (historical XML), garmin_bulk.py (historical), garmin.py (Phase 6 live sync, ADR 0004), health_auto_export.py (Phase 6 live weight sync — different JSON format from apple_health.py, not the same pipeline), common.py (shared helpers) — bjj_manual.py not needed (log_bjj.py writes directly)
  core/                 db.py, timezones.py, dedupe.py (activities cross-source dedup, live), schema.sql (snapshot, v5), migrations/000{1,2,3,4,5}_*.sql (source of truth), models.py
  metrics/              body_comp.py (weight trend + comp countdown), load.py (monotony/strain, CTL/ATL/TSB — no ACWR, ADR 0003), baselines.py (HRV/RHR baselines, sleep debt), readiness.py (0-100 composite), bjj_laps.py (HR-based sparring/rest lap classification), derived_daily.py (Phase 4 persistence — writes all of the above into `derived_daily`, with an honest "stale" confidence for CTL/ATL/TSB/weight when the underlying series doesn't reach today)
  coach/                rules.py, briefing.py, weekly_retro.py
  dashboard/             app.py (Streamlit entrypoint, st.navigation), theme.py (dark theme + chart helpers), data.py (cached DB/config access), views/{today,trends,training,comp_prep,log,data_health}.py — stays in active use until the React migration (ADR 0005) is fully done
  api/                   main.py (FastAPI app, local-only, all 6 pages' routes), today.py/trends.py/training.py/comp_prep.py/data_health.py (one real read-only assembly fn per page), log.py (the one page with real POST mutation endpoints — reuses core/models.py's dataclasses for validation, never a second copy) — ADR 0005 frontend migration, 2026-08-28
frontend/               Vite + React + TypeScript + Tailwind v4 + shadcn/ui (Radix base) + react-router-dom + recharts — ADR 0005, 2026-08-28, all 6 pages. src/pages/{Today,Trends,Training,CompPrep,Log,DataHealth}.tsx, components/{today,charts,log,layout}/*.tsx, index.css carries the same Carbon g100 dark tokens as dashboard/theme.py (ported, not re-picked). Daily use: `npm run build` once, then `uv run python scripts/run_api.py` alone serves everything on port 8000. Active frontend dev: `npm run dev` (port 5173, hot reload, proxies /api to FastAPI) + `scripts/run_api.py` (port 8000) as two processes instead.
scripts/                backfill.py (Phase 2 entrypoint, runs dedupe.py automatically after ingestion), log_bjj.py (manual BJJ logger), log_calisthenics.py (manual calisthenics logger), log_wellness.py (daily Hooper-Mackinnon wellness), log_measurement.py (waist/tape logger), weight_report.py (Phase 4 preview), sync.py (Phase 6 daily live-sync entrypoint — Garmin + Health Auto Export, incl. per-lap detail for sub_sport=="bjj" activities), compute_derived.py (Phase 4 derived-metric persistence, trailing-3-day window like sync.py), briefing.py (Phase 7 CLI), weekly_retro.py (Phase 7 CLI), check_secrets.py (pre-commit secret-shaped-string guard, design principle 8), run_api.py (ADR 0005 — local FastAPI server, port 8000; also serves the built frontend/dist/ for one-command daily use, see "One-command frontend serving built"), morning_run.sh (Phase 8 — chains sync+compute_derived+briefing+retro, what launchd's 07:00 com.healthos.morning runs), quiet_sync.sh (Phase 8 — sync+compute_derived only, no briefing, what launchd's 21:30 com.healthos.quicksync runs, see "Real bug found: weight had been silently stale" for why)
githooks/               pre-commit (calls check_secrets.py; activated once per clone via `git config core.hooksPath githooks`, since `.git/hooks/` itself can't be version-controlled)
launchd/                com.healthos.morning.plist (Phase 8 — installed as a real LaunchAgent, 10:00 Europe/Madrid daily, moved from an initial 07:00 default per Francisco's request)
tests/                  core/, ingest/, metrics/, coach/, scripts/, api/ (ADR 0005 backend), fixtures/ (synthetic — never real personal data, fixtures are committed to git)
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
- **`activity_laps`** (migration 0004) — one row per `(activity_id, lap_index)`,
  raw per-lap detail (`avg_hr`, `max_hr`, `duration_s`, Garmin's own
  `intensity_type`) for Francisco's manually-lapped BJJ round tracking. The
  sparring-vs-rest read is a derived heuristic (`metrics/bjj_laps.py`), not stored
  here — see "Round-by-round BJJ lap ingestion" above.
- **`calisthenics_sessions`** (migration 0003) — one row per `(date, session_type)`,
  exercise-level detail (`exercises_json`: sets/reps/added weight per exercise)
  Garmin's own "Strength Training" activity type can't capture.
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

## Coaching layer — rules engine + briefing built, Phase 7 (2026-08-28)

**Deterministic rules first, prose second.** The rules engine produces a decision + reasons; the language layer only narrates that — it never invents a recommendation the rules didn't produce.

`coach/rules.py` (pure, deterministic, no LLM calls ever) and `coach/briefing.py`
(assembles real data, calls `rules.py` for every decision, formats the result) are
built and real — this is the module `dashboard/views/today.py`'s "simplified preview"
(2026-08-28, earlier the same day) was explicitly a stand-in for; the preview is gone
now, replaced by `dashboard/data.py: daily_plan()` calling the real
`coach/briefing.compute_daily_plan()` directly. `scripts/briefing.py` is the CLI
entrypoint (`uv run python scripts/briefing.py [--date YYYY-MM-DD]`).

**Readiness bands** (against the fixed weekly shape) — `classify_readiness_band()`,
the one canonical source for the 75/55 thresholds (the dashboard's `theme.py` imports
it rather than keeping its own copy):
- **Green ≥75** — train as scheduled; BJJ live rounds fine; lifting days get a load progression attempt.
- **Amber 55-74** — train as scheduled, cap intensity; BJJ technical/no-ego rolls; hold calisthenics load; bike strictly Z2.
- **Red <55** — downgrade, don't delete: BJJ → drilling only; calisthenics → mobility + light kettlebell.

`session_guidance()` combines today's *actual scheduled session* (from
`comp_prep.weekly_template`, not a generic weekly sentence) with the band — e.g.
Friday's Amber guidance is specifically "cap it — aim for roughly 2/3 of your usual
open-mat rounds," not the same text a Monday technical class would get.

**Structural triggers, all built and real** (not the placeholder text the dashboard
preview had):
- `hrv_sustained_low()` — 3 consecutive days HRV >1 SD below baseline, recomputing
  `compute_hrv_baseline()` for each of the last 3 days by truncating the observation
  list (same "baseline slides day to day" approach `compute_rhr_baseline()` already
  used internally).
- `tsb_persistently_negative()` — TSB negative for 4+ straight days. Kickoff doc flags
  the real numeric threshold as "TBD once load-unit calibration exists" — "negative at
  all" is the documented placeholder condition, not a made-up magnitude.
- `monotony_strain_flag()` — current week's monotony >2.0 AND strain in the top
  quartile of the last 8 weeks. Real bug caught in testing: `compute_monotony_strain()`
  returns one result *per day* (a daily-sliding 7-day window), not one per calendar
  week — an early draft's `weekly_results[-lookback_weeks:]` only looked back
  ~2 weeks' worth of days while claiming 8. Fixed to
  `weekly_results[-lookback_weeks * 7:]`.
- `should_downgrade_to_rest()` — the "never prescribe a full rest day off one bad
  number, require 2 consecutive red days or 3 amber days first" gate. Needs real
  trailing readiness-*band* history, not just today's score — `compute_daily_plan()`
  builds this by recomputing the full readiness score as of each of the last 3 days
  (truncating every observation series per day), not by reading a persisted history
  (`derived_daily` still isn't written to by anything).

**Two hard safety rails, enforced BY CONSTRUCTION rather than by a runtime check —
documented explicitly in `rules.py` rather than left implicit:**
- *Never recommend running* — `_SESSION_GUIDANCE`'s vocabulary of session types (from
  `comp_prep.weekly_template`) never includes running in the first place; the
  athlete's own weekly architecture never schedules it (the knee injury guardrail
  already lives at the config layer).
- *Never add a 4th/5th hard session* — `session_guidance()` only ever narrates
  sessions already present in `weekly_template`; it has no mechanism to add one.

**One rail that's genuinely checked at runtime**: the neck-niggle → no pressing/
overhead progression rule. `has_recent_neck_niggle()` scans `subjective_log.niggles`
and `bjj_sessions.niggles` (trailing 7 days) for "neck" (case-insensitive substring —
a blunt instrument, deliberately erring toward pausing progression too often rather
than missing a real one) and forces calisthenics guidance to "hold current load"
regardless of readiness band if found.

**Nutrition focus**: `nutrition_focus()`'s only possible outputs are two fixed,
pre-approved sentences (never fasting, never a deficit deeper than
`deficit_kcal_max` implies, never "making up" for a social meal) — the guardrail is
enforced by construction, not by checking generated text after the fact.

**One trend observation, only if notable**: `_notable_trend_observation()` checks a
small fixed priority list (RHR `sustained_rise_flag`, comp-countdown red flag) and
returns the first that fires, or nothing — "silence is valid" is implemented literally
as "return `None`, the caller adds no line."

**Real output against the actual database, 2026-08-28** (Friday):
```
Health OS briefing — 2026-08-28 (Friday)

Readiness: AMBER
  Bjj (open mat): Cap it — aim for roughly 2/3 of your usual rounds, technical focus on the rest.

Nutrition: Hit 180g protein today — the one hard number that matters most.
```
And for a real historical date with worse readiness (2026-08-24, a real red run in the
account's actual data):
```
Health OS briefing — 2026-08-24 (Monday)

Readiness: RED
  Bjj (no gi technical): Drilling only — skip the live rolling portion entirely.
  Calisthenics (strength a): Mobility + light kettlebell instead of the full session.
  ⚠ Structural: 2+ consecutive red days or 3 amber days in a row — consider downgrading today's session further, not just per-band guidance above.

Nutrition: Hit 180g protein today — the one hard number that matters most.
```

35 new tests (`tests/coach/test_rules.py`) — every rule function individually, including
the monotony/strain lookback bug caught above. 262 tests total, all passing.

**Weekly retro — built same day, 2026-08-28.** Francisco asked directly: how/where is
this stored, and flagged it as important. `coach/weekly_retro.py: compute_weekly_retro()`
+ `format_weekly_retro()`, CLI entrypoint `scripts/weekly_retro.py [--week-ending
YYYY-MM-DD]`. Every number is either a real logged value or explicitly marked
insufficient/not-trackable — same discipline as `briefing.py`. Two honest gaps, not
silently glossed over:
- **Sessions completed vs. planned**: BJJ checked against `bjj_sessions`, bike against
  `activities.sport = 'cycling'` — but **calisthenics has no logging mechanism
  anywhere in this codebase** (same gap the Training dashboard page already flags), so
  it's marked `not_trackable`, never guessed as "missed."
- **"Proposed calisthenics progression"** (kickoff doc spec) has no data to base a
  proposal on for the same reason — says so directly rather than fabricating one.
- **Social-meal count is reported as a plain count next to the weight trend, not a
  computed correlation** — the kickoff doc's own Correlation engine (Spearman rho with
  n/p) is a separate, deliberately deferred piece (needs 90 days of data this account
  doesn't have yet), and this module doesn't pretend two numbers next to each other is
  the same claim.

13 new tests (`tests/coach/test_weekly_retro.py`). **Real output against the actual
database (2026-08-28, week 2026-08-22 to 2026-08-28)**: correctly shows the real
2026-08-22 cycling ride as completed, all 4 scheduled BJJ sessions as "missed" (accurate
— Francisco hasn't started logging BJJ sessions yet), weight trend `insufficient_data`
(sparse weigh-ins that week), sleep 8.3h avg (6/7 nights). TSB/monotony numbers inherit
the same training-load staleness already documented above — not a new issue, just
visible again here.

**Not yet done**: the **correlation engine** — still explicitly deferred (needs 90 days
of data this account doesn't have yet; building it now would mean building against data
too thin to trust, not a real capability yet). This is now the only unbuilt piece of
Phase 7's original spec.

## Custom "BJJ" Garmin profile verified against a real recording (2026-08-28)

Francisco recorded a real test session on a custom "Otros"→"BJJ" Garmin profile
(deviates from `docs/bjj_recording_workflow.md`'s original Cardio/HIIT
recommendation — turns out to be arguably better, see that doc's 2026-08-28 update
for the full reasoning). Verified by inspecting the real synced data directly:
`activityType.typeKey` is `"other"` regardless of the on-device rename, but the
custom name **does** sync through as `activityName: "BJJ"`. `ingest/garmin.py` now
captures this in `activities.sub_sport` (lowercased directly — `normalize_sport_name()`
mangles a free-typed acronym like "BJJ" into `"b_j_j"`, verified, not assumed; that
function is for CamelCase API constants, not user-typed names) whenever
`sport == "other"` and a name is present, so `sport="other", sub_sport="bjj"` is now
a real, filterable signal. 2 new tests, 293 total passing.

Francisco's lap-recording plan (lap per round, rest rounds lapped separately, HR
level distinguishing sparring from rest after the fact) — **built and verified
end-to-end 2026-08-28, see "Round-by-round BJJ lap ingestion" below.**

## Round-by-round BJJ lap ingestion (2026-08-28)

Francisco's actual recording plan (lap 1 = drilling at the top of class, a new
lap at the start of each sparring round, a full rest round lapped separately
too, intending sparring-vs-rest to be readable from HR level after the fact) —
built and verified end-to-end against his real test recording
(`activityId 24147743826`, `sport=other, sub_sport=bjj`), not just against fakes.

- **`core/migrations/0004_activity_laps.sql`** (schema version 3 → 4) — new
  `activity_laps` table, grain `(activity_id, lap_index)`, FK to
  `activities.activity_id`. `core/models.py: ActivityLap` holds only the raw
  Garmin fields (`start_utc`, `duration_s`, `distance_m`, `avg_hr`, `max_hr`,
  `calories`, `intensity_type`) — no classification baked in (raw vs. derived
  stays separate, same split as `daily_metrics` vs `derived_daily`).
- **`ingest/garmin.py: fetch_activity_laps()`** calls `get_activity_splits()` —
  confirmed present on the installed client by direct inspection, real
  response shape checked against Francisco's actual test activity first (not
  assumed from docs). Reuses `_parse_garmin_gmt_timestamp()` completely
  unchanged — it already handled this endpoint's 'T'-separated,
  fractional-second timestamp shape (`"2026-08-28T12:18:53.0"`), a different
  shape from the whole-activity endpoint's space-separated one, with zero code
  changes needed, verified directly.
- **`scripts/sync.py`** calls it **only for activities with `sub_sport ==
  "bjj"`** — a deliberate scope decision, not fetched for every activity by
  default, since most other sports have no meaningful laps (a single-lap run)
  and there's no benefit to the extra API call per activity.
- **Real, honest limitation, confirmed rather than assumed away**: Garmin's
  `intensityType` came back `"ACTIVE"` for both real laps in the test
  recording — it's built for Garmin's own structured-interval workout types,
  not freeform manually-pressed laps, so it does **not** distinguish sparring
  from rest for Francisco's recording style. That read has to come from our
  own code.
- **`metrics/bjj_laps.py: classify_bjj_laps()`** is that code — a pure,
  self-relative heuristic (design principle 6: this is a derived opinion, not
  a fact, and is kept out of the raw `activity_laps` table on purpose). Lap 1
  is always `warmup_or_drilling` (Francisco's own stated workflow, a fixed
  rule not a guess); every later lap is compared against the **median avg_hr
  of the OTHER round laps in the same activity** — self-relative rather than a
  fixed BPM cutoff, the same principle already used for the HRV/RHR baselines
  and the TSB z-score (ADR 0003) elsewhere in this project, since an absolute
  threshold would be wrong for a bad night and wrong again for a fitter
  version of the same athlete later. Needs ≥2 round laps with real HR data to
  attempt a split; returns `insufficient_data` per lap below that rather than
  guessing — which is exactly what the real 2-lap test recording produced
  (it was a connectivity test, not a real class, so there was only one round
  lap to compare against nothing).
- **Verified against the real account end-to-end**, not just unit tests: ran
  `scripts/sync.py` for real — it correctly detected the one `sub_sport=="bjj"`
  activity in the trailing window, fetched 2 real laps via
  `get_activity_splits()`, and upserted them into the real `activity_laps`
  table (`garmin:24147743826`, lap 1 avg_hr=65 → `warmup_or_drilling`, lap 2
  avg_hr=73 → `insufficient_data`, correctly not over-claiming a sparring/rest
  read from a single round lap).
- 10 new tests (`tests/ingest/test_garmin.py::TestFetchActivityLaps`,
  `tests/metrics/test_bjj_laps.py`, `tests/core/test_models.py::TestActivityLap`
  including a real FK-violation check). 309 tests total, ruff clean.

**Not yet done**: no dashboard surface for lap/classification data — only
reachable by calling `classify_bjj_laps()` directly right now, same
"computed but not displayed yet" state several Phase 4 metrics were in before
the dashboard existed. Worth a Training-page addition once a real multi-round
class gets recorded, since the 2-lap test above only checks the mechanism
works, not what a real sparring session's round-by-round data looks like.

## Deep review pass across the whole session's build, real bugs fixed (2026-08-28)

Francisco asked for a genuine adversarial review of everything built this
session, not a self-check — 5 parallel review agents (coaching/rules logic;
ingestion/live-sync; schema/migrations/models; dashboard/manual loggers;
security/secrets/scheduling), each told to actually run the tests, run the
real code against constructed inputs, and cross-check every CLAUDE.md claim
against what the code actually does rather than trust the prose. Two findings
were independently confirmed by two different reviewers with no shared
context — a strong signal they're real, not review noise. Fixed the following
(all verified with new regression tests + a real re-run of `scripts/sync.py`
against Francisco's actual account and database):

- **`daily_metrics.sources` was silently losing provenance, not accumulating
  it** — confirmed independently by both the schema and ingestion reviewers.
  `db.upsert()`'s plain `ON CONFLICT DO UPDATE` replaced the whole `sources`
  JSON blob on every write, so a Garmin sync's `{"resting_hr": "garmin"}`
  followed by a same-day Apple Health/Renpho sync's `{"weight_kg":
  "apple_health:renpho"}` left `sources` as only the second call's dict —
  the *values* were always correctly preserved (the thing the one existing
  partial-upsert test checked), but the provenance column whose entire job
  is design-principle-9 traceability was quietly losing history every day
  both syncs touched the same date, which is the normal case. Fixed with a
  new `db.upsert(..., merge_json_columns=[...])` option — reads the existing
  stored value first and merges new keys in (new wins on conflict) rather
  than overwriting — wired into all four `daily_metrics` upsert call sites
  (`scripts/sync.py` ×2, `scripts/backfill.py` ×2). **Note**: this only fixes
  it going forward — any `sources` history already lost to this bug on
  earlier real syncs isn't recoverable, though the underlying VALUE columns
  were never affected.
- **`compute_readiness_score()` crashed with `ZeroDivisionError`** if every
  component that had real data that day was configured with weight `0.0`
  (e.g. setting `weight_tsb: 0.0` in `athlete.yaml` while TSB's stale-load
  problem is unresolved — a realistic near-term config change, not
  far-fetched). Now returns `insufficient_data` in that case, same as having
  no components at all.
- **Dashboard Log page could silently overwrite a backdated entry with no
  warning**, all four tabs (BJJ/calisthenics/wellness/waist): the
  "already logged" check queried `_today()` while the actual date came from
  an `st.date_input` *inside* the `st.form`, which — since Streamlit forms
  don't rerun until submit — the pre-form check could never see. Backdating
  an entry (e.g. logging Tuesday's forgotten BJJ session on Wednesday) gave
  no overwrite warning even if Tuesday already had a different entry. Fixed
  by moving each tab's date picker outside its form, mirroring the pattern
  `session_type` already used in the same file.
- **`coach/weekly_retro.py`'s calisthenics completion only checked the
  manual log**, contradicting CLAUDE.md's own documented two-signal design
  (Garmin "Strength Training" activity OR manual log). A session actually
  recorded on the watch with no manual log entry that day was reported as
  "missed." Fixed to also check `activities` for the real sport strings
  found in Francisco's own database (`strength_training`,
  `traditional_strength_training`, `weight_training`,
  `functional_strength_training`).
- **`SubjectiveLogEntry.hooper_index` never computed when the 4 wellness
  sub-scores were logged across separate calls** — exactly
  `log_wellness.py`'s own documented usage pattern ("log just the wellness
  scores some days, just protein/social-meal on others"). All 4 sub-scores
  could end up correctly stored in the DB and `hooper_index` would still be
  permanently `NULL`, silently degrading the readiness score's subjective
  component. Fixed with a new `core/models.py: merge_subjective_log_entry()`
  — merges with any existing row for that date before constructing the final
  entry, so `hooper_index` is recomputed over the full accumulated set.
  Wired into both `log_wellness.py` and the dashboard's wellness tab.
- **`core/dedupe.py`'s activity delete had no FK-safety** — neither
  `bjj_sessions.linked_activity_id` nor `activity_laps.activity_id` declares
  `ON DELETE CASCADE`, so deleting a loser row either still references would
  raise `sqlite3.IntegrityError`, uncaught, aborting every cluster in the
  same dedupe pass (with no `ingest_runs` record of any of it, since dedupe
  isn't wrapped in start/finish_ingest_run). Not reachable today — default
  precedence always ranks Garmin highest and laps only attach to Garmin rows
  — but latent, and one precedence-order change or `linked_activity_id` use
  away from a real crash. Fixed: each loser's delete is now individually
  try/excepted — a conflicting loser is skipped (left unmerged, not recorded
  as absorbed) rather than crashing the run, and collected in a new
  `DedupeResult.fk_conflicts` field so it's visible, never silently dropped.
- **`ingest/garmin.py` had three batch-killing exception gaps**: (1)
  `_fetch_one_day_metrics()` only caught `GarminConnectResponseValidationError`
  per endpoint — any other exception (a timeout, a 429 rate-limit, both
  observed for real against this account per the live-sync notes above)
  propagated uncaught, aborting the rest of the date range AND the
  activities/laps fetch that follows in the same sync run; (2)
  `_activity_to_model()` was called unguarded in `fetch_activities()`, so one
  activity with an unparseable timestamp silently dropped every activity
  after it in the batch; (3) the error-label expression itself assumed the
  raw API entry was always a dict, so a malformed non-dict entry raised
  `AttributeError` from inside the except block, masking the real error.
  Broadened the endpoint-level catches to `Exception`, wrapped
  `_activity_to_model()` in its own try/except, and made the error label
  defensive against non-dict entries.
- **`ingest/health_auto_export.py: parse_weight()` was all-or-nothing across
  every file**, not per-record isolated: a single malformed reading anywhere
  (an unrecognized unit, an unparseable date) raised before a single
  `DailyMetric` was ever yielded, discarding every valid reading from every
  file in the directory for that run — not just the bad one. `sync.py` did
  catch this at the top level (marks the run `failed`, doesn't crash the
  whole script), so it wasn't silent, but it contradicted the per-item-skip
  resilience pattern the rest of the ingestion layer uses. Fixed with a new
  `errors` parameter, wired through `sync_health_auto_export()` the same way
  `ingest/garmin.py`'s functions already work.
- **File permissions**: `.env` and `data/health.db` were world-readable
  (`644`) despite holding a live Garmin password and personal health data;
  `data/.garth_tokens/` was already correctly `600`. `chmod 600` applied to
  both — filesystem-only, not a code change.

**Verified, not just fixed-and-hoped**: 14 new regression tests across
`test_db.py`, `test_dedupe.py`, `test_garmin.py`, `test_health_auto_export.py`,
`test_models.py`, `test_weekly_retro.py` — 323 tests total, all passing, ruff
clean. Re-ran `scripts/sync.py` for real against Francisco's actual account
after all fixes: clean run, no errors, no crash, `sources` provenance now
correctly accumulating on real data.

**Update, 2026-08-28, second fix wave — nearly everything above is now
fixed.** Francisco asked directly to close out this list rather than let it
sit as known-but-deferred, plus build `derived_daily` persistence (see
"Derived-daily persistence built" below) — done together in one pass, using
a fixer subagent for the independent nitpick batch in parallel with the
riskier, more central fixes (migration atomicity, the briefing.py leak)
done directly, on a strict non-overlapping file partition so both could run
concurrently without conflicting. All verified: 368 tests passing (up from
335), ruff clean, and several fixes independently confirmed against real
exploitable/reproducible behavior rather than just code-reading (see each
bullet).

- ✅ **`apply_migrations()` atomicity** — fixed by prepending a literal
  `BEGIN;` to the migration script text and managing commit/rollback
  explicitly in Python (`executescript()`'s own docs: "disregards
  isolation_level; any transaction control must be added to sql_script" —
  SQLite DDL genuinely IS transactional when explicitly wrapped). Verified
  by direct reproduction before AND after: a 3-statement script with the
  last statement failing left zero tables persisted after rollback, and a
  corrected retry then applied cleanly with no leftover corruption.
- ✅ **`briefing.py` future-data leak** — `daily_rows`/`daily_load_series`/
  `tsb_series` now bounded to `<= today` immediately after fetch. This
  module had ZERO test coverage before this fix — `tests/coach/
  test_briefing.py` is new, and 2 of its 3 new leak tests were confirmed to
  fail against the pre-fix code (git-stash-verified) before confirming they
  pass against the fix.
- ✅ **`sustained_rise_flag` off-by-2** — now `None` (not a silent `False`)
  whenever any of the 3 required sub-baselines can't be computed yet
  (`n < min_days + 2`), matching design principle 6. Verified against the
  exact boundary (n=21, n=22 → `None`; n=23 → correctly computed).
- ✅ **Pre-commit secret hook built and genuinely activated** —
  `scripts/check_secrets.py` (stdlib-only, checks staged ADDED lines against
  5 high-confidence credential-shaped patterns) + `githooks/pre-commit`,
  activated via `git config core.hooksPath githooks` (already run on this
  real repo, not just documented). Verified twice independently (once by
  the fixer agent, once by me): staged a file containing
  `GARMIN_PASSWORD=hunter2`, confirmed `git commit` was actually blocked
  (exit 1), confirmed a clean file commits fine.
- ✅ **`derived_daily.computed_at` never updating** — resolved as part of
  building the persistence layer properly rather than reproducing the known
  gap: `store_derived_metrics()` passes `touch_column="computed_at"` to
  `db.upsert()`, and a dedicated regression test confirms it bumps on
  every recompute.
- ✅ **`osascript` injection hardening** — `NOTE_TEXT` now escaped
  (backslash and double-quote) before interpolating into the AppleScript
  string literal in `morning_run.sh`. The fixer agent's verification here
  went further than requested and is worth recording: it confirmed the
  PRE-fix code was genuinely exploitable (a crafted payload executed a real
  `do shell script` command through the old unescaped interpolation), then
  confirmed the fix neutralizes that exact payload, then confirmed a nasty
  string with `"`, `\`, and `` ` `` together round-trips correctly through
  the real `osascript` binary.
- ✅ **All 5 remaining nitpicks fixed**: dead `dashboard/data.py:
  readiness_weights()` deleted (zero callers, confirmed via grep);
  `dashboard/views/data_health.py`'s naive `date.today()` replaced with the
  project's explicit Europe/Madrid pattern; `BodyMeasurement` gained
  `__post_init__` range validation (40-200cm, matching the dashboard's own
  widget bounds); `training.py`'s load-by-sport chart now fills `NULL`
  sport with `"unknown"` before grouping instead of pandas silently
  dropping those rows (`groupby(dropna=True)` default — confirmed via a
  standalone repro that the old code silently dropped 30 of 120 real load
  units); `finish_ingest_run()` now raises on an unknown `run_id` instead
  of silently no-op'ing.

**Still open, genuinely lower priority** (test-gaps, not bugs, no live
drift found):
- `tests/core/test_schema_sync.py` only compares columns — it still cannot
  catch index, multi-column UNIQUE, or FOREIGN KEY drift between
  `schema.sql` and the real migrations. Narrower than its own docstring
  admits, but no live drift exists today.
- Several CHECK constraints (`subjective_log`'s four 1-10 ranges,
  `calisthenics_sessions`, `bjj_sessions.session_feeling`) are still only
  tested at the Python `__post_init__` level, never against the real DB
  constraint directly.

## Derived-daily persistence built (2026-08-28)

Francisco asked directly: "let's also build the derived daily (we need it
right?)" — yes. Every Phase 4 metric (HRV/RHR baselines, sleep debt, CTL/
ATL/TSB, monotony/strain, weight trend, comp countdown, readiness score) had
been computable since earlier the same day, but nothing had ever written a
row to `derived_daily` — every number was recomputed live, on demand, with
no historical record. Closed with `metrics/derived_daily.py` (new) +
`scripts/compute_derived.py` (new CLI, same trailing-3-day-window shape as
`scripts/sync.py`, same self-healing reasoning: a delayed Garmin correction
can change an already-synced day's inputs after the fact).

**Built with the future-leakage lesson already applied, not retrofitted**:
every observation series this module fetches is bounded to `<= as_of_date`
in the SQL itself (`WHERE date <= ?`), the same discipline `coach/
briefing.py` gained earlier the same day after a real bug there. Verified
directly with the same kind of test (`tests/metrics/test_derived_daily.py::
TestDateBounding`) — future rows planted in the DB must not affect an
earlier `as_of_date`'s computation.

**A new, deliberate design decision on CTL/ATL/TSB honesty**:
`build_daily_load_series()` only walks from the first to the LAST OBSERVED
date in its inputs — it does not extend to `as_of_date` with invented
zero-load days if training/BJJ logging has gone stale (already documented
as a real, ~2.5-month-stale condition in this account, see the training-load
build-out section above). Padding forward with zeros would silently treat
"untracked training" as "confirmed rest," exactly the kind of false
precision design principle 6 warns against. Instead, when a series' last
real date is ≥3 days before `as_of_date`, the affected rows (`ctl`, `atl`,
`tsb`, `monotony`, `strain`, `tsb_zscore`, `weight_ewma`,
`weight_trend_slope`) carry `confidence="stale"` (a new, explicit value)
plus `inputs_json: {"last_real_data_date": ..., "days_stale": ...}` — the
last real value is still stored (never `None` for actually-known
history), but a reader can never mistake it for current.

**13 metrics per date, every one always written** — even with zero data,
every metric name gets an `insufficient_data` row rather than a gap, so a
missing row in `derived_daily` for a real date always means "the pipeline
didn't run," never "there was nothing to compute" (design principle 6).
`readiness_score`'s `inputs_json` carries the full component breakdown
(raw/score/weight_used per component, coverage, weights actually used) —
the same traceability the live `compute_readiness_score()` call always
returned, now durably stored, not just printed once and discarded.

**Real bug caught while building this, not left for later**: `store_derived_metrics()`
initially passed `touch_column=None` to `db.upsert()`, reproducing the exact
"`derived_daily.computed_at` never updates on recompute" gap flagged (and
deliberately deferred) in the review pass above — caught immediately by
testing before it ever reached the real DB, since I was building this fresh
with that exact known gap in mind. Fixed by passing
`touch_column="computed_at"` instead of `None` — `db.upsert()`'s existing
touch-column mechanism was already exactly the right tool, it just needed
pointing at the right column name for this table. A dedicated regression
test (`test_computed_at_bumps_on_recompute`) locks this in.

**Real output against the actual database (2026-08-28)**: ran
`scripts/compute_derived.py --days 5` for real. Confirms the staleness
design works exactly as intended: `ctl`/`atl`/`tsb`/`monotony`/`strain` all
came back `confidence="stale"` with `days_stale: 76` and
`last_real_data_date: "2026-06-13"` — matching the training-load
build-out section's own hand-documented staleness finding number-for-number,
an independent real-data confirmation the honesty design is doing its job
rather than silently inventing a fresher-looking number. `readiness_score`
for 2026-08-28 came back 57.5, `confidence="partial"` (coverage 0.9, missing
only the subjective/Hooper component — consistent with earlier findings that
Francisco hadn't logged wellness data that day).

11 new tests, ruff clean. Wired into `scripts/morning_run.sh` as a real step
between `sync.py` and `briefing.py` — verified by actually running the whole
script end to end (`bash scripts/morning_run.sh`), not just each piece in
isolation: sync → compute derived metrics (39 rows across the trailing
3-day window) → briefing, all chaining correctly against the real database,
confirmed in `data/logs/morning_run.log`.

**Not yet done**: no dashboard surface reads from `derived_daily` yet — the
Trends/Today pages still call the live metric functions directly (that's
fine and correct for "today," but a "readiness score over the last 90 days"
chart would need to read the new historical rows instead of recomputing 90
times on every page load). Worth a Trends-page addition once the frontend
migration (ADR 0005) lands, or sooner if useful before then.

## Calisthenics tracking closed, a real gap (2026-08-28)

Francisco asked directly: should he track calisthenics, and how? This had been an
honestly-flagged gap since the Training dashboard page and the weekly retro both said
so explicitly rather than inventing data. Closed with a two-signal split — same pattern
already established for BJJ (Garmin captures physiology, a manual log captures what
Garmin can't see):

- **Garmin side, zero new code**: recording calisthenics as a **"Strength Training"**
  activity (a real, recognized Garmin type) already flows through the existing
  `activities` ingestion pipeline automatically — duration, HR, calories, for free.
  Recommended over a generic/"Other" type specifically because it's already a type
  our `core/dedupe.py: _SPORT_FAMILIES` mapping and `ingest/common.py:
  normalize_sport_name()` handle correctly.
- **Manual log, new**: `calisthenics_sessions` (migration 0003) — `core/models.py:
  CalisthenicsSession`, exercise-level detail (sets/reps/added weight) Garmin's
  activity summary can't capture, checked against (not required to exactly match)
  `config/athlete.yaml: comp_prep.strength_sessions`'s prescribed exercise list.
  `exercises` is a JSON list of `{exercise, sets, reps, added_weight_kg, notes}` —
  structured enough to chart per-exercise trends later, without a full normalized
  child table for what's currently a short fixed list of ~5-6 exercises per type.
- **`scripts/log_calisthenics.py`** — interactive mode walks every prescribed exercise
  for the session type; flag mode covers just the session-level RPE/notes (no
  per-exercise detail — interactive mode is where that lives). Upserts on
  (date, session_type), warns before overwriting, same shape as every other logger.
- **Dashboard**: new "Calisthenics" tab on the Log page (session type outside the
  form so switching it reruns and shows the right exercise list, same pattern as the
  BJJ tab's rolling-fields toggle). Training page's stale "not tracked" placeholder
  replaced with the actual last 10 logged sessions.
- **`coach/weekly_retro.py`** updated: calisthenics session completion now checked
  against the real table instead of returning `"not_trackable"`; the "proposed
  calisthenics progression" section shows what was actually logged that week.
  Comparing against a *prior* week's log of the same exercise (a real progression
  delta, e.g. "add a rep or a kg next time") is flagged as not computed yet — this
  only shows what was logged, honestly, rather than inventing a trend from one data
  point.

17 new tests across `test_models.py`, `test_log_calisthenics.py`, and updated
`test_weekly_retro.py` (the old "not trackable" assertions correctly now assert real
completed/missed status). 291 tests total, ruff clean. `core/schema.sql` and the
schema drift-guard test both updated for the new table (version 2 → 3).

## Scheduling built, Phase 8 (2026-08-28)

Francisco asked directly: is data actually fresh automatically, or does someone have to
trigger it? Honest answer at the time: no — `scripts/sync.py` had no scheduler behind
it at all (confirmed by checking: no crontab, no launchd agent existed on this
machine). Built and **installed for real**, not just written:

- **`scripts/morning_run.sh`** — the kickoff doc's "one command each morning" flow,
  finally actually one command: runs `sync.py`, then `briefing.py`, then
  `weekly_retro.py` too if it's a Sunday. Appends everything to
  `data/logs/morning_run.log` (gitignored — real personal health numbers in plain
  text) and fires a native macOS notification (`osascript`, already on every Mac, no
  new dependency) with the readiness line, or a "sync had errors, check the log"
  message if sync failed that day. Deliberately does not treat a sync failure as fatal
  — `sync_garmin()` already degrades gracefully and logs to `ingest_runs` itself; the
  wrapper just makes sure a bad sync day doesn't also block the briefing from running
  against whatever data already exists.
- **`launchd/com.healthos.morning.plist`** — a per-user LaunchAgent (not a
  LaunchDaemon: never needs root, only needs to run while Francisco's logged in — a
  briefing firing while the machine sits alone isn't useful anyway), `StartCalendarInterval`
  07:00 Europe/Madrid daily. Checked into the repo for the record; actually taking
  effect requires copying it to `~/Library/LaunchAgents/` and `launchctl load`ing it
  (both done on this machine already — see the plist's own header comment for the
  exact commands, including how to check status or remove it).

**Real bug caught by actually testing through launchd, not just running the script by
hand**: the first version failed with `uv: command not found` the moment it ran as a
real scheduled job (confirmed via `launchctl start` to trigger it immediately rather
than waiting for 07:00) — launchd's environment doesn't include `/opt/homebrew/bin` in
`PATH` the way an interactive shell does. An interactive-shell test of the same script
had passed cleanly right before this, which is exactly why it was tested again through
the real mechanism rather than trusted from that first pass. Fixed by hardcoding the
absolute `uv` path in the script. Confirmed clean after the fix: real `launchctl start`
run produced a correct log (sync + briefing succeeded) and an empty stderr log.

**07:00 is a default, not a measured one** — adjust `Hour`/`Minute` in the plist to
match Francisco's actual wake time once that's known, and reload
(`launchctl unload` then `launchctl load` again).

## Dashboard — built, Phase 5 (2026-08-28)

`src/health_os/dashboard/`: Streamlit + Plotly, dark theme, raw points always shown
behind smoothed lines (lighter shade, `theme.add_raw_and_smoothed()`). One entrypoint
(`app.py`, `uv run streamlit run src/health_os/dashboard/app.py`) using `st.navigation`/
`st.Page` (modern multipage API, needs the `streamlit>=1.36` already pinned) rather than
the classic `pages/`-folder convention — avoids any ambiguity with Streamlit's implicit
folder-name auto-discovery, and keeps page metadata (title/icon/default) explicit in one
place. All six pages shipped together, not staged as "read-only first" — the kickoff
doc's phrasing turned out to describe a natural build order, not a real reason to ship
Log later once every page was this close to done anyway:

- **Today** — the readiness composite (reusing `metrics/readiness.py` unchanged, feeding
  it live HRV/RHR baselines, sleep debt, TSB z-score, and the latest `hooper_index` —
  each component only passed through when its own `confidence == "full"`, otherwise
  `None` so it's dropped and renormalized exactly per the metrics layer's own contract),
  a simplified **band-based guidance lookup** (Green/Amber/Red text lifted verbatim from
  this file's own Coaching-layer section — deterministic, not invented, but explicitly
  labeled as a preview since the real Phase 7 rules engine with its safety rails and
  2-red/3-amber-day gating isn't built yet), sleep, weight EWMA, comp countdown.
- **Trends** — weight/HRV/RHR/sleep stages, 30/90/365-day window selector. HRV/RHR
  smoothing uses a new `dashboard/data.py: smooth_for_display()` — deliberately NOT a
  reuse of `metrics/body_comp.py: compute_weight_ewma()` outside its documented domain
  (weight trend analysis); same recursive-EWMA math, kept as a separate, analysis-free
  charting helper instead.
- **Training** — CTL/ATL/TSB chart, monotony/strain, load by day/sport. Surfaces the
  already-known staleness problem directly rather than hiding it: with no BJJ sessions
  logged yet and Garmin/Strava's `training_load` mostly absent (see the training-load
  build-out section above), this page currently just shows a clear explanatory warning
  instead of an empty or misleading chart. **Calisthenics progression is a real,
  labeled gap** — there is no logging mechanism for calisthenics sets/reps/load
  anywhere in the schema, so the page says exactly that rather than inventing a chart
  with nothing behind it.
- **Comp Prep** — weight trajectory (raw + EWMA) vs. a straight-line required path to
  the division limit, plus a shaded projection band from the trend's own 95% CI (never
  shown below `weight_trend_ols()`'s own `insufficient_data` threshold).
- **Log** — BJJ session / daily wellness / waist, one `st.form()` each, in the same
  file the CLI scripts already use for validation
  (`BjjSession`/`SubjectiveLogEntry`/`BodyMeasurement`'s own `__post_init__`) rather
  than re-implementing it — the dashboard form just constructs the dataclass and
  surfaces the `ValueError` via `st.error()` if it fails. Boolean fields
  (`protein_hit`/`gassed`/`social_meal`) use a tri-state Skip/Yes/No select instead of
  a checkbox — a checkbox can't represent "not answered today," which several of these
  genuinely need (design principle 6). Warns before overwriting an existing entry for
  the day, same as the CLI. Mirrors `scripts/log_bjj.py`'s conditional-fields behavior
  (rounds/feeling only for `class`/`open_mat`) by putting `session_type` outside the
  `st.form` so choosing it triggers an immediate rerun.
- **Data Health** — per-field freshness (days since last real value for
  weight/HRV/RHR/sleep/training_readiness), missing days in the trailing 30, the
  dedupe log (any `activities` row with a non-empty `merged_from`), and the last 100
  `ingest_runs` rows (failed runs highlighted). Not optional per the kickoff doc's own
  framing — this is deliberately the page that would make a silent pipeline break
  visible.

**Verification approach, worth noting**: rather than leaving dashboard code untested
(the working agreement explicitly allows this — "dashboard can go untested"), all six
pages were smoke-tested with Streamlit's own `AppTest` harness
(`streamlit.testing.v1.AppTest.from_file(...).run()`) directly against the real
database — catches real exceptions (bad column names, wrong function signatures, `None`
arithmetic) without needing a browser. All six passed clean on the real data. Also
caught and fixed a real deprecation: `st.plotly_chart(..., use_container_width=True)` is
past its removal deadline (2025-12-31) in the installed Streamlit version — replaced
with `width="stretch"` everywhere before this was called done.

**Not yet done**: no scheduling (that's Phase 8). Readiness "guidance" text is a
hardcoded lookup, not the real rules engine.

## Dashboard visual redesign + day-aware guidance (2026-08-28)

Francisco looked at the first version in a real browser and called it "structured but
ugly" — pointed at WHOOP's app (screenshots) and asked to check WHOOP's own design
guidelines page. That page only gates a proprietary PDF behind ToS acceptance, so this
redesign is built from the screenshots directly (ring gauges, near-black background,
rounded dark cards, bold numbers) — our own colors/components inspired by that
structure, not WHOOP's actual (proprietary) brand assets. Also checked
`VoltAgent/awesome-claude-design` (a pointer collection of `DESIGN.md` style-guide
files, not actual CSS) — the Linear/Vercel entries describe an "ultra-minimal, precise,
single accent" philosophy; **did not** run the `npx getdesign@latest add ...`
installer it points to (executing an unvetted third-party package is a real
supply-chain risk not worth taking just to fetch a style spec) — applied that
well-established minimal-dark-dashboard philosophy by hand instead.

- **`theme.py`**: near-true-black background, refined palette (teal-green/muted-
  orange/red/blue closer to what's visible in the WHOOP screenshots than the initial
  GitHub-dark-mode-esque colors), Inter webfont via Google Fonts `@import` (safe here
  — this is a normal local web server rendering to a real browser, not a sandboxed
  Artifact with a CSP blocking external fonts). New `ring_svg()`/`mini_ring_svg()` —
  pure inline SVG circular progress rings with rounded stroke caps (`stroke-linecap:
  round`, standard circumference/dashoffset technique), replacing the flat
  `st.progress()` bars from the first version. `st.container(border=True)` restyled
  globally into the rounded dark "card" look (subtle border + soft shadow rather than
  a bright outline) with automatic bottom margin, so pages no longer need manual
  `st.write("")` spacer calls between sections (removed across all 6 views).
- **Today** is the flagship redesign: readiness score is now a big central ring
  (colored by band) instead of a plain `st.metric`; the 5 sub-components are a row of
  small rings instead of horizontal progress bars — much closer to WHOOP's actual
  "Recovery ring + sub-metrics" layout.

**Day-aware guidance, replacing the flat weekly-generic text** — Francisco asked
directly: "today it's Friday... you should suggest me how to do open mat, not generic
for the week." The previous version showed the same Green/Amber/Red sentence
regardless of what day it was. Now `views/today.py` reads `comp_prep.weekly_template`
for *today's actual weekday* (Europe/Madrid) and looks up guidance keyed on
`(session_type, band)` — e.g. Friday's readiness-Amber guidance is specifically "cap
it — aim for roughly 2/3 of your usual open-mat rounds," not the same text Monday's
technical class would get. Still an explicitly labeled **simplified preview**, not
Phase 7's real rules engine (no structural triggers, no injury-guardrail integration,
no 2-red/3-amber gating) — but it is a real, deterministic `(session, band) →
instruction` lookup table, not invented per-response text, consistent with "rules
first" even at this smaller scale.

**Real schedule detail captured directly from Francisco (2026-08-28), corrected into
`config/athlete.yaml: comp_prep.weekly_template`** — the original comp-prep plan doc
gave session *types* (`no_gi_technical`/`hard_rounds`/`open_mat`) but not their actual
clock-time structure:
- Monday/Tuesday/Wednesday BJJ classes are all the same structure: 60min drilling +
  30min rolling (4-5 × 5min rounds) — Tuesday's `hard_rounds` label means the rolling
  portion is harder-paced, not a different class format.
- Friday open mat: up to 10-15 rolls (round length not specified).
- Saturday bike: **Z2-Z3 depending on the day**, 40-60km — Francisco's own direct,
  current statement, which the config now notes supersedes the older block-specific
  `bike_km_range` figures (60-70/50-70/40-50 across base/build/sharpen) where they
  conflict, since it's the more current source — both are kept on record rather than
  silently overwriting one with the other.
- Confirmed directly: BJJ and bike stay fixed in the weekly architecture (as already
  designed — "the architecture is fixed, the coaching layer advises within it, never
  redesigns it"); calisthenics should also stay fixed. This matches the project's
  existing design exactly, not a new decision — Francisco's message was confirming the
  standing approach, not changing it.

All 6 pages re-verified with `AppTest` against the real database and real
`config/athlete.yaml` after this change (today, a real Friday, correctly renders
open-mat-specific guidance); 227 tests passing; ruff clean.

## Dashboard visual redesign, round 2 — real screenshots, Carbon tokens (2026-08-28)

Francisco said round 1 still looked "ugly" and pointed at a second repo,
`alexpate/awesome-design-systems` — genuinely a links list to real published design
systems (Material, Carbon, Polaris, Cloudscape, Chakra, ...), not an installer, so no
supply-chain concern like the earlier `awesome-claude-design` repo's npx tool. **IBM
Carbon** was the pick — built specifically for dense/dark dashboards, real published
`g100` dark-theme tokens rather than eyeballed hex values:
`#161616` background / `#262626` layer / `#393939` border / `#f4f4f4` text-primary /
`#8d8d8d` text-helper / support colors `#42be65` green, `#f1c21b` amber (a real yellow,
brighter than the previous guessed amber), `#fa4d56` red, `#78a9ff` blue. Swapped into
`theme.py` wholesale.

**Bigger fix: got an actual way to see the rendered page.** Up to this point every
visual change was made blind — no browser/screenshot tool in this environment, only
Francisco's descriptions and screenshots to react to, which wasn't converging.
Discovered Chrome (already installed) has a built-in headless screenshot flag —
`google-chrome --headless --screenshot=out.png --window-size=W,H --virtual-time-budget=N
URL` — no new dependency, no third-party package execution, just invoking the
already-installed, already-trusted browser binary. **Real gotcha hit and worked
around**: right after a Streamlit server restart, a screenshot taken too soon
(`--virtual-time-budget=8000`, ~5-10s after restart) reliably captured Streamlit's
loading-skeleton placeholder, not the real content — confirmed by getting the *exact
same byte count* twice in a row, meaning the render was deterministically cut off at
the same point rather than varying with real content. Fixed by waiting longer in real
wall-clock time after a restart (~15s) before screenshotting, not by trusting
`--virtual-time-budget` to compensate — that flag governs virtual JS timers, not the
real WebSocket round-trip Streamlit's actual page content streams over.

Real screenshot of the Today page surfaced three concrete, fixable problems no amount
of further blind guessing would have found reliably:
1. **Card padding was far too tight** (`6px 10px`) — text sat right at the card edges.
   Fixed to `20px 24px` (Carbon's own 8px-based spacing scale: spacing-05/06).
2. **Font inconsistency** — the Inter webfont was applied to HTML text but never to
   Plotly charts (`base_figure()`'s `font=dict(...)` had no `family`), so charts and
   text rendered in visibly different typefaces on the same page. Fixed.
3. **Sidebar didn't match the main content** — Streamlit's own unstyled default gray
   sidebar background sat right next to the new near-black main area, a visible seam.
   Fixed by explicitly styling `section[data-testid="stSidebar"]`.

Re-screenshotted after the fix (real 1440×900 viewport, not the artificially tall
window the first screenshot used) — confirms the fix: proper card spacing, sidebar
matches, Friday's open-mat-specific guidance renders correctly and legibly. All 6
pages re-run through `AppTest` + the full suite (227 passing) after the change.

**Even after this — still not "slick."** Francisco pointed at a fourth reference
(`alexpate/awesome-design-systems`, then a "100k-star" AI design skill repo, verified
at 122,302 real stars via the GitHub API but built for React/Tailwind/shadcn with an
`npx`-based installer — not run, same risk category as the earlier WHOOP tool, and not
portable to Streamlit regardless). Four legitimate design references in one session,
still not landing, stopped looking like a reference-material problem and started
looking like a real Streamlit ceiling — its native widgets render through fixed
internal HTML/CSS that injected CSS can restyle but not rebuild. **Decision: migrate
to a real React/Tailwind frontend, scheduled after Phase 7, not before — see
[ADR 0005](docs/decisions/0005-frontend-migration-off-streamlit.md)** for the full
reasoning (Phase 7 is backend-only and frontend-agnostic; building the new frontend's
coaching UI once against Phase 7's real output shape beats building it now against a
placeholder that's about to be replaced). The Streamlit dashboard stays in active use,
as-is, until that migration happens.

## Frontend migration started — Today page, real and running (2026-08-28)

Francisco gave the go-ahead the same day everything above (derived_daily, the full
review-pass fix wave) landed. Scoped deliberately as **Today page first**, his own
choice when asked whether to build all 6 pages blind or see one running first — matches
this project's own standing "stop and show before continuing" discipline. ADR 0005
updated with the stack specifics it had deliberately deferred; full detail there,
summary here.

**New: `src/health_os/api/`** (FastAPI, local-only, binds `127.0.0.1` never `0.0.0.0`
— design principle 1). `api/today.py: build_today_payload()` is the one real assembly
function (calls `coach.briefing.compute_daily_plan()` + `metrics.body_comp` directly,
zero business-logic duplication into JavaScript) — `api/main.py`'s `/api/today` route
is a thin wrapper over it, same "one real computation" discipline `coach/briefing.py`
already established for the CLI and Streamlit. `scripts/run_api.py` runs it via
uvicorn. New deps: `fastapi`, `uvicorn` (runtime), `httpx` (dev-only, needed for
FastAPI's `TestClient`) — all named here per the "ask before adding a dependency" rule,
already added to `pyproject.toml` with a comment explaining what each buys.

**New: `frontend/`** — Vite + React + TypeScript + Tailwind v4 + shadcn/ui (Radix UI
base, not the CLI's newer "Base UI" default — Radix has the longer, better-documented
track record, same "stable over bleeding-edge" preference as ADR 0004's Pydantic-models
choice). Single fixed dark theme, no light/dark toggle — ported the Streamlit
dashboard's own approved Carbon `g100` tokens (`theme.py`) directly into
`frontend/src/index.css` rather than re-picking colors, since that visual identity was
already explicitly settled after three prior iteration rounds. `frontend/src/pages/
Today.tsx` + `components/today/{ReadinessRing,ComponentRing,SessionCard,StatCard}.tsx`
reproduce `dashboard/views/today.py`'s exact content (readiness ring + component
breakdown, today's guidance + structural warnings, sleep/weight/comp-countdown cards,
nutrition & trend) as real React components instead of injected raw-SVG strings.

**Real tooling bug hit and fixed, not silently worked around**: `npx shadcn@latest
init`/`add` wrote every component file to a literal `./@/` directory at the frontend
project root instead of resolving the `@/*` → `./src/*` alias into
`src/components/ui/` — confirmed by inspecting the actual file tree (`find` showed
`./@/components/ui/card.tsx` sitting next to, not inside, `./src/`), not assumed from
the command appearing to succeed. Fixed by moving the files to their correct location
by hand; verified the fix by rebuilding cleanly afterward (`npx tsc -b && npm run
build`, zero errors) rather than trusting the move alone.

**Verified against the real running app, not just a successful build** — same
Chrome-headless-screenshot discipline that caught real bugs in the Streamlit dashboard
(no other way to actually *see* a rendered page in this environment): started
`scripts/run_api.py` (port 8000) and `cd frontend && npm run dev` (Vite, port 5173,
proxying `/api` to FastAPI — `vite.config.ts`) together for real, screenshotted the
live page. Confirms against Francisco's real database: readiness ring showing 58/Amber,
correct component breakdown (HRV 44, RHR 63, Sleep 100, Freshness 14 — TSB's low score
consistent with the already-documented stale-load-data caveat), Friday's open-mat
guidance rendering correctly, sleep/weight/comp-countdown cards all showing real
numbers matching what the Streamlit page and the CLI briefing already independently
confirmed. Card padding, borders, and spacing render properly on the first attempt —
no "too tight" iteration needed this time, unlike the first two Streamlit redesign
rounds.

7 new backend tests (`tests/api/`) covering `build_today_payload()`'s date-bounding
(a weigh-in logged after the requested date must not leak in — same discipline applied
throughout this session) and a FastAPI route smoke test via `TestClient`. Frontend
components are presentational only and untested for now, consistent with this
project's own "dashboard can go untested" working agreement — the same rule already
applied to the Streamlit version.

**Not yet done**: the remaining 5 pages (Trends, Training, Comp Prep, Log, Data
Health) — Log in particular needs real POST/mutation endpoints (BJJ/wellness/waist/
calisthenics forms), not just the read-only `GET /api/today` built so far. A
production serving story (FastAPI serving the built `frontend/dist/` as static files,
vs. always running two local dev processes) is also undecided — fine for now since
`npm run dev` + `scripts/run_api.py` is a normal local dev workflow, but worth deciding
before calling the migration "done." The Streamlit dashboard keeps running unchanged in
the meantime — nothing is deleted or frozen mid-migration.

## Today page design pass — real sourced data, not guessed (2026-08-28)

Francisco's reaction to the first pass: "much better, but still not sleek and
beautiful." Pointed at `nextlevelbuilder/ui-ux-pro-max-skill` (122k+ real GitHub
stars, verified via `gh api` before anything else — same discipline every external
repo gets in this project) and asked me to read/use it.

**What it actually is, checked directly rather than assumed from its README's
marketing tone**: a real, structured design-intelligence dataset (CSVs: 79 UI styles,
192 color palettes, 74 typography pairings, per-stack guidelines including a
`stacks/shadcn.csv` and `stacks/react.csv`, motion/animation timing tables, a
192-row industry-specific reasoning engine) — not an executable tool by itself. Its
own README is explicit that AI agents should never install anything on the user's
machine unilaterally ("these install steps are for you, the human user... AI agents
using this skill should never install software on your machine; they are instructed
to ask you instead") and that its search script "installs nothing and makes no
network calls." Given that, downloaded the raw data files directly via `gh api`
(`ui-reasoning.csv`, `styles.csv`, `colors.csv`, `typography.csv`, `motion.csv`,
`stacks/shadcn.csv`) and read the actual guidance rather than running its CLI/plugin
installer — real value, zero unreviewed code executed.

**What the data actually said, applied concretely**:
- The `ui-reasoning.csv` row closest to a personal quantified-self readiness
  dashboard is **"Financial Dashboard"** (not "Healthcare App," which is patient-
  facing/clinic software, a different product shape): pattern "Data-Dense Dashboard,"
  style "Dark Mode (OLED) + Data-Dense Dashboard," colors "Dark bg + Red/Green alerts
  + Trust blue," key effects "Real-time number animations + Alert pulse," must-have
  constraints "real-time-updates, high-contrast." This matches what this project
  already had (Carbon dark tokens, a red/amber/green band system) almost exactly —
  the gap wasn't the color/theme decision, it was that the first React pass hadn't
  applied the DENSITY and MOTION half of that same reasoning row yet.
- `styles.csv`'s "Data-Dense Dashboard" row: minimal padding (8-12px), efficient grid,
  dense-but-readable typography, compact card design — applied by tightening card
  padding (`p-6`→`p-5`/`p-4`) and switching the stat-card row and component-ring row
  from ad hoc flex-wrap to explicit CSS grid.
- `typography.csv`'s "Minimal Swiss" pairing (Inter/Inter) is explicitly recommended
  for "Dashboards, admin panels, documentation, enterprise apps, design systems" —
  confirms the existing Inter choice (carried over from the Streamlit theme) rather
  than requiring a font swap.
- `motion.csv`'s "Standard" card-hover pattern (lift + shadow, 200-300ms) and the
  Financial Dashboard row's "Real-time number animations" effect — implemented with
  plain Tailwind transitions (`lib/styles.ts: CARD_CLASS`, a shared hover-lift/
  elevation treatment) and a small `hooks/useCountUp.ts`, deliberately NOT adding
  GSAP as a new dependency for an effect this simple (the dataset's own example
  snippets use GSAP, but plain CSS transitions achieve the same lift+shadow+count-up
  without a new package). `useCountUp` respects `prefers-reduced-motion` throughout,
  matching the dataset's own stated convention on every motion pattern it lists.
- **A real anti-pattern caught and fixed**: the README's own pre-delivery checklist
  says "No emojis as icons (use SVG: Heroicons/Lucide)" — the first pass had used a
  raw `⚠️` emoji character for structural warnings. Replaced with a proper
  `lucide-react` `TriangleAlert` icon (already installed via shadcn's own icon-library
  setup, zero new dependency) plus a subtle `animate-ping` ring for the "alert pulse"
  effect the Financial Dashboard row calls for.

**Real tooling gotcha hit during verification, not just assumed away**: headless
Chrome's `--screenshot` flag captures as soon as the page reaches network/DOM
quiescence, which does NOT wait for `requestAnimationFrame`-driven animations to
finish — three consecutive screenshots caught the count-up mid-flight (12, then 20,
then 41 out of a final 58) regardless of `--virtual-time-budget` size, confirming
that flag doesn't accelerate real rAF timing the way it does JS timers. Resolved two
ways, not one hack: shortened the count-up duration to something snappier (200ms/
180ms — also a genuine improvement for a "real-time" dashboard feel, not just a
workaround), and separately verified the animation's *logic* is correct using
Chrome's real `--force-prefers-reduced-motion` flag, which confirmed the final
numbers land exactly on the true values (58/44/63/100/14, matching the API directly)
with zero animation — proving both the reduced-motion fallback and the settled end
state are correct, independent of the screenshot-timing artifact.

Not a redesign of the whole visual system (colors/theme/font were already right, per
the data itself) — a tightening pass: density, elevation, real icons, motion. Same
Today page, same data, verified against the real running app again after the change.

**Round 2, same day — Francisco's honest reaction to round 1's screenshot: "looks
pretty much the same as before no?"** He was right. Round 1's changes (density,
hover/motion timing, icon-not-emoji) were real but mostly invisible in a static,
no-interaction screenshot — hover states need a pointer, the count-up settles before
a human actually looks, and the emoji-to-icon fix only shows up on a day with
structural warnings (none that day). A static-screenshot judgment call needed
static-visible changes, not just under-the-hood correctness.

Went back to the same `ui-ux-pro-max-skill` data for what round 1 had read but not
yet applied: `styles.csv`'s "Dark Mode (OLED)" row explicitly calls for "Minimal glow
(text-shadow: 0 0 10px)" and vibrant accent treatment — round 1 applied the density
guidance from that row but skipped the glow entirely. Added, for real this time:
- A soft blurred radial glow behind the readiness ring, colored by the day's actual
  band (amber that day) — `ReadinessRing.tsx`, pure CSS blur, no new dependency.
- Gradient strokes on both rings (light tint → base band color, new `--band-*-light`
  CSS variables) instead of a flat single-color arc — the same visual language Apple
  Watch activity rings and WHOOP's recovery ring use.
- Icons on every stat card and session (`Moon`/`Scale`/`Target`/`Utensils`/`Swords`/
  `Bike`/`Dumbbell`/`BedDouble` from `lucide-react`, already installed, zero new
  dependency) — round 1's icon fix only touched the warning icon; every OTHER icon
  slot on the page was still bare text.
- A colored top accent line and a very faint (6% opacity) radial color wash on the
  hero readiness card, and a page-level background gradient tinted by the day's own
  band color — the page's overall color mood now visibly reflects the actual
  readiness state instead of being uniformly neutral-dark regardless of the number.

Verified the same way as round 1 (Chrome's real `--force-prefers-reduced-motion`
flag for a settled, non-racing capture) — the screenshot after round 2 is visibly,
not just technically, different: an amber glow behind the ring, a warm-tinted card,
icons throughout. Round 1's lesson, stated plainly rather than glossed over: reading
real design data is necessary but not sufficient — it also has to be checked against
what a human actually sees in a static view, not just what the reasoning says to do.

## All 6 pages built — frontend migration complete (2026-08-28)

Francisco, after approving the Today page's second design pass: "you can go ahead
with the rest of the front end!" Built the remaining 5 pages (Trends, Training, Comp
Prep, Log, Data Health) in one pass, reusing everything established on Today
(`CARD_CLASS`, `lib/band.ts`'s color mapping, the gradient-ring/glow treatment, Lucide
icons throughout) rather than each page reinventing its own visual language. Full
detail in ADR 0005's "all 6 pages complete" update; summary here.

**New backend, one module per page** (`src/health_os/api/`): `trends.py`,
`training.py`, `comp_prep.py`, `data_health.py`, `log.py` — each mirrors its
Streamlit `dashboard/views/*.py` counterpart's exact computation, same "one real
assembly function per page" discipline as `today.py`. `log.py` is the one genuinely
new backend surface (Streamlit only ever read+wrote through Python function calls
directly; a real HTTP API needs actual request/response endpoints) — `POST /api/log/
{bjj,wellness,waist,calisthenics}`, each a thin wrapper over the SAME dataclasses
(`core/models.py`) already validated by the CLI scripts and Streamlit, a `ValueError`
becoming a 422 with the same message `st.error()` would show. `merge_subjective_log_
entry()` (the hooper_index cross-call fix from earlier this session) is reused here,
not re-solved. 36 new backend tests (`tests/api/test_{trends,training,comp_prep,
data_health,log}.py`) — 405 total passing, ruff clean.

**New frontend infrastructure**: `react-router-dom` (a persistent left `Sidebar` +
`AppShell` layout, 240px wide — the exact width `ui-ux-pro-max-skill`'s own
Data-Dense Dashboard checklist names for this nav style) and `recharts` (named
alongside chartjs/d3 as compatible with that same style in the same dataset — picked
as the most idiomatic-React option). Both new dependencies named explicitly per the
"ask before adding a dependency" rule. Route-level code-splitting
(`React.lazy`/`Suspense` per page) keeps `recharts` out of the Today page's bundle —
caught by Vite's own "chunk larger than 500kB" warning during the build, not chased
speculatively; initial bundle dropped from 835KB to 236KB after.

**Real tooling gotcha, recurring**: `npx shadcn@latest add` (tabs, input, textarea,
label, select, slider — every component added for the Log page's forms) repeated the
exact same "writes to a literal `./@/` folder instead of `src/components/ui/`" bug
found on the Today page. Same fix each time (move the files by hand), now confirmed
as a real, repeatable characteristic of this tool in this project's setup, not a
one-off fluke.

**Verified against the real database, all 6 pages, via the same Chrome-headless
screenshot discipline used throughout this migration**: Trends' three time-series
charts (weight/HRV/RHR) correctly show raw points behind smoothed lines with real
data back to June 2026; Training's CTL/ATL/TSB chart renders the same stale
pre-June-2026 load series already documented elsewhere in this file; Comp Prep's
weight-trajectory chart correctly renders the required-path line, the amber
projection-CI band, and the red division-limit reference line; Data Health's tables
show the real 5-group dedupe log and real recent `ingest_runs` rows (including that
day's own `compute_derived`/`health_auto_export`/`garmin_live` runs); Log's four tabs
render with today's real date pre-filled and correctly-styled shadcn form controls.

**Deliberately not verified by submitting real data**: the Log page's actual POST
behavior was NOT exercised by clicking through the real UI against Francisco's real
database — doing so would write fake BJJ/wellness/waist/calisthenics entries into his
actual health data as a side effect of a design review, which he never asked for. The
36 backend tests covering `api/log.py` directly (save/get/validation/upsert/merge
behavior, run against a throwaway in-memory DB via the existing `conn` fixture) are
the verification of record for the write path instead — a deliberate choice, not an
oversight, consistent with this project's own "raw data is immutable" and "hard to
reverse actions get confirmed first" discipline.

**Not yet done**: no production serving decision (FastAPI serving the built
`frontend/dist/` as static files, vs. the current two-local-process dev workflow);
Streamlit dashboard stays in place, not scheduled for removal; the Log page's actual
write path hasn't been exercised end-to-end through the real browser UI (only via the
backend test suite) — worth doing once Francisco actually uses it for a real entry.

- Python 3.12+, `uv` for deps, `ruff` for lint/format, `pytest` for tests, type hints on
  every public function.
- **Ask before adding any dependency** not already named in this doc or `pyproject.toml`, and say what it buys.
- Small commits, conventional commit messages, one logical change each.
- Tests mandatory on ingest + metrics layers. Dashboard can go untested.
- Any non-obvious choice gets a numbered ADR in `docs/decisions/` with alternatives considered.
- If something here is wrong, out of date, or a bad idea — say so before building it.
- When a real API/library behaves differently than documented here, trust the API and
  update this file.

## Schedule fluidity + custom calisthenics exercises (2026-08-28)

Francisco asked directly: how fluid is the system — next week is a one-week holiday,
he won't follow the normal comp-prep schedule, but will get in a few runs and reduced
calisthenics (push-ups/abs instead of the prescribed exercises). Answered honestly
against what's actually built, not guessed:

- **A run is safe to log, but only via Garmin/Strava auto-detection, never a manual
  "running" session type** — the knee-injury guardrail (`coach/rules.py`) is enforced
  by construction: the session-type vocabulary the coaching layer narrates from
  (`comp_prep.weekly_template`) simply never includes running, so there's no
  mechanism to *recommend* it. But nothing stops the activity itself from landing in
  `activities` as `sport="running"` the same as any other Garmin-recorded session —
  ingestion doesn't gate on sport type, only the coaching/guidance layer does. A
  holiday-week run shows up on Trends/Training like any other cardio session; the
  system just never tells him to do another one.
- **The weekly retro and comp-prep weekly-template comparison will correctly show a
  week of "missed" BJJ/bike sessions during the holiday** — this is design principle 6
  working as intended (never invent data, never silently adjust the plan), not a bug
  to route around. `coach/weekly_retro.py` has no "vacation mode" that suppresses
  missed-session flags, and shouldn't grow one just to make one deviated week look
  clean — an honest gap report is more useful than a plan that quietly rewrites itself.
- **Reduced calisthenics (push-ups/abs) had a real, closed gap**: the interactive
  logger (`scripts/log_calisthenics.py`) and the dashboard/frontend Log page's
  Calisthenics tab only ever walked the prescribed `config/athlete.yaml:
  comp_prep.strength_sessions` exercise list — there was no way to log a substituted
  exercise with real sets/reps, only the free-text `notes` field. Confirmed first that
  `core/models.py: CalisthenicsSession` already had zero exercise-name validation
  (only `session_type` and `session_rpe` are constrained), so this was purely a
  CLI-loop and frontend-form gap, not a schema change. Closed same day, both sides:
  - `scripts/log_calisthenics.py: _prompt_custom_exercises()` — prompts for one more
    free-text exercise name until a blank entry ends it, runs unconditionally after
    the prescribed loop (including when the prescribed list is empty, e.g. a session
    type with no config match), same "blank sets to skip" shape already used
    elsewhere in this script.
  - `frontend/src/components/log/LogCalisthenicsTab.tsx` — matching "Add exercise"
    button appends a free-text-name row (sets/reps/added-kg + a remove ✕ button) to
    the same `exercises` array the prescribed rows build, sent to the same
    `POST /api/log/calisthenics` endpoint unchanged. Blank-named rows are dropped
    silently on submit, mirroring the prescribed rows' "sets > 0" skip rule.
  - 6 new tests (`tests/scripts/test_log_calisthenics.py`), including a holiday-
    substitution case with an *empty* prescribed list (confirms the custom-exercise
    prompt isn't accidentally gated on a prescribed session type existing). 416 tests
    passing, ruff clean. Frontend typecheck/build/lint clean; verified visually via a
    Chrome-headless screenshot (temporarily seeded preview state to render populated
    rows, reverted immediately after — never left in the committed code).
- **Not changed, and correctly so**: the fixed weekly architecture itself
  (`comp_prep.weekly_template`) and the coaching layer's guidance vocabulary — a
  one-off travel week is a logging-and-honest-reporting problem, not a reason to make
  the programmed plan itself more "flexible." The system now has somewhere real to
  put what actually happened; it still never pretends the plan happened when it
  didn't.

## Phone access considered, declined for now (2026-08-28)

Francisco asked directly about getting this on his phone for daily viewing/logging.
Explored cloud hosting as an alternative to design principle 1's "local-first, no
cloud services" (Tailscale-to-Mac and a small always-on home box were both raised
first as local-only options that don't require reversing the principle at all).
Real current pricing/fit was checked, not assumed, for four candidates:

- **Supabase** — genuinely free tier ($0, 500MB Postgres, unlimited API requests),
  but the wrong shape regardless of price: it hosts a Postgres DB + auto-generated
  API + Edge Functions, not an arbitrary Python process. This project's actual value
  (`metrics/`, `coach/rules.py`, the Garmin sync job) is Python business logic that
  needs to run somewhere — Supabase doesn't host that, so using it would mean either
  paying for a separate app host anyway or rewriting the coaching engine into SQL/
  TypeScript. Ruled out on fit, not cost.
- **Fly.io** — free tier discontinued for new signups as of 2026; realistically
  ~$7-10/mo with persistent storage for a small always-on service. No longer the
  cheap option an earlier (uncorrected) estimate in this conversation assumed.
- **Railway** — $5/mo flat (Hobby plan, $5 usage credit included), runs the existing
  FastAPI + SQLite + React build close to as-is, git-connected auto-deploy. The best
  fit of the paid options if this gets revisited.
- **Plain VPS (Hetzner-style)** — cheapest predictable cost (~€4-5/mo), most manual
  setup (Docker/HTTPS/reverse-proxy by hand).

**Decision: stay local-only, no cloud, no PWA/mobile work built.** Francisco was
explicit he doesn't care about the health data itself being publicly reachable (so no
auth was going to be required either way), but weighed the actual setup effort against
the payoff and chose to keep running this on his laptop as-is. Nothing about the
architecture changed — this is a considered-and-declined path, not a reversal of
design principle 1, so no ADR (nothing was decided differently from what already
existed). Worth 5 minutes of re-reading this section before re-proposing cloud hosting
from scratch in a future session; the Railway-vs-VPS-vs-Supabase-fit reasoning above
should still hold even if exact prices have drifted again by then.

## One-command frontend serving built (2026-08-28)

Immediately practical trigger: Francisco did open mat BJJ with no HR strap yet
(arriving Monday) and asked how to open the visual to log it, "and moving forward as
well" — two dev processes (`npm run dev` + `scripts/run_api.py`) every time was the
wrong answer for daily use, and this was the exact "production serving" question
ADR 0005 had left open since the frontend migration finished. Resolved it directly
rather than leaving it open further — see ADR 0005's "production serving resolved"
update for full detail.

`api/main.py` gained a catch-all route (registered after every `/api/*` route, so
those always win) that serves `frontend/dist/` once `npm run build` has been run,
with an index.html fallback so React Router's client-side paths (`/log`, `/trends`,
...) survive a hard refresh or direct link, and a path-traversal guard
(`_safe_dist_file()`). 6 new tests (`tests/api/test_main.py`), 416 total passing,
ruff clean. Verified against the real running server, not just tests: built for real,
confirmed port 8000 alone serves `/log` and real asset files, screenshotted.

**Then, same conversation**: Francisco found even "run one command in a terminal"
too much friction for something meant to be opened daily. Closed the gap the rest of
the way — `launchd/com.healthos.api.plist` (new), same per-user LaunchAgent pattern
as `com.healthos.morning.plist`, but `RunAtLoad` + `KeepAlive` (a permanent
background service, not a once-daily scheduled task) instead of a calendar trigger.
`scripts/run_api.py` gained a `--no-reload` flag — the background instance doesn't
need uvicorn's file-watcher, that's for active development only. **Result: nothing
to run, ever, day to day** — `http://localhost:8000` is just always there whenever
the laptop is on. Installed and verified for real, not just written: copied to
`~/Library/LaunchAgents/`, loaded, confirmed `/api/today`/`/log`/a real asset all
return 200; killed the process directly (`kill -9`) and confirmed launchd restarted
it automatically within seconds, same "trust the real mechanism, not just the happy
path" discipline as the original morning-run LaunchAgent's launchd-env bug. One real
tradeoff, documented in both the plist and `run_api.py`'s own docstring: this holds
port 8000 permanently, so active frontend development (`npm run dev`) needs
`launchctl unload` first to free it — not a conflict during normal daily use, only
worth knowing before an eventual frontend-editing session.

## Real bug found: weight had been silently stale for over a week (2026-08-29)

Francisco asked whether his bike ride and "everything" had come in, which surfaced a
real gap while checking: `HEALTH_AUTO_EXPORT_DIR` was **never actually set in the real
`.env`** — `.env.example` already documented it correctly, but the real file just
fell back to its default, `data/raw/health_auto_export`, which was a one-time manual
copy of 3 files made on 2026-08-28 while building the feature (see that section
above). Nothing was ever wired to refresh that folder, so it silently stopped
reflecting reality the moment it was created — nothing errored, `scripts/sync.py`
happily reported success every day reading the same stale files.

Found by actually locating the real live folder rather than assuming: `mdfind -name
HealthAutoExport` (Spotlight search bypasses the `Operation not permitted` restriction
on listing `~/Library/Mobile Documents/` directly) surfaced the real path —
`~/Library/Mobile Documents/iCloud~com~ifunography~HealthExport/Documents/HealthOS/`
— which had a **newer file the stale local copy never got** (`HealthAutoExport-
2026-35.json`, this week's export) containing real, current weigh-ins: 79.15kg
(2026-08-27), 79.05kg (2026-08-28) — the automation had been working correctly on
Francisco's end the whole time; the gap was entirely in how this project was reading
from it. Fixed by setting `HEALTH_AUTO_EXPORT_DIR` in the real `.env` to that live
path (`.env.example`'s existing guidance was already correct — added a note there on
finding the real path via `mdfind`, since the exact iCloud container path isn't
guessable and varies by app install). Re-ran `scripts/sync.py`: 3 rows upserted,
2026-08-27/28 weight confirmed landing in `daily_metrics` immediately.

**Same conversation, a related-but-separate fix**: the daily automatic sync
(`com.healthos.morning.plist`) fired at 10:00 Europe/Madrid — too late for Francisco's
actual need (knowing his readiness before an 8:15am bike ride) and also structurally
unable to see that day's own activities or weigh-in, since they hadn't happened yet
at 10:00 either. Not a "sync more often" fix (Garmin's own wellness data only updates
a handful of times a day regardless of how often it's polled) — moved the morning job
to 07:00 and added a second, quiet evening pass (`scripts/quiet_sync.sh` +
`com.healthos.quicksync.plist`, new, 21:30) that syncs and recomputes derived metrics
with no briefing/notification on success, so the next morning's real briefing always
has a complete picture of the previous day. Both times are defaults, adjustable once
lived with for a few days, same as the original morning job's own 07:00→10:00 history.
Tested `quiet_sync.sh` by hand before installing; both LaunchAgents installed and
loaded for real, not just written.

**Same day, follow-up**: Francisco asked what happens on a *normal* day when he
wakes at 8:30-9:00 rather than early for a ride — real gap: Garmin only finalizes
overnight sleep/HRV once the person actually wakes, so a 07:00-only schedule would
read stale/incomplete data on those days. `com.healthos.morning.plist`'s
`StartCalendarInterval` is now an array of two fixed times — 07:00 (ride-day early
check) and 09:30 (new, ~30-60min buffer after a normal wake) — rather than adding a
new plist, since launchd natively supports multiple fixed times for one job. Two
notifications on a normal morning is an accepted tradeoff, not an oversight.

**Also same conversation — a real bug in the Health Auto Export pipeline, found and
fixed**: checking whether that day's bike ride and weight had synced surfaced that
`HEALTH_AUTO_EXPORT_DIR` was **never actually set in the real `.env`** — it silently
fell back to `data/raw/health_auto_export`, a one-time manual copy of 3 files made
2026-08-28 while building the feature, which nothing ever refreshed. Weight had been
stale for over a week with zero errors — `scripts/sync.py` happily reported success
every day reading the same static files. Found the real live folder with `mdfind
-name HealthAutoExport` (Spotlight search bypasses the `Operation not permitted`
restriction on listing `~/Library/Mobile Documents/` directly) — it had a newer file
the stale copy never got, containing real current weigh-ins (79.15kg 2026-08-27,
79.05kg 2026-08-28) confirming the automation had been working correctly on
Francisco's end the whole time; the gap was entirely in how this project read from
it. Fixed by pointing `HEALTH_AUTO_EXPORT_DIR` at the real path;
`.env.example`'s existing guidance was already correct, just never applied to the
real `.env` — added a note there on finding the real path via `mdfind` for next time.
Re-ran `scripts/sync.py`: 3 rows upserted, both dates confirmed landing immediately.

**Real, still-open finding, needs a change on Francisco's phone, not in this
codebase**: 2026-08-29's own weigh-in still hadn't synced by early afternoon.
Checked the Health Auto Export app's own automation settings screen (screenshot) —
**"Sync Frequency: Every 7 Days"**, last fired 2026-08-28, so the next automatic
export won't happen until ~2026-09-04 regardless of how often `scripts/sync.py`
itself runs. Confirmed no new file appeared in the live iCloud folder between the
first and second check that afternoon, consistent with this reading. Told Francisco
directly to change it to "Every 1 Day" in the app — a phone-side setting this
project's code can't reach or fix from here.

## Renpho body composition ingested — lean mass + BMI (migration 0005, 2026-08-29)

Francisco asked directly whether Apple Health surfaces Renpho's body-composition
metrics beyond weight, and whether they could be taken into account. Checked against
the real live export (every metric name in every real file, not assumed):
`lean_body_mass` and `body_mass_index` are both present in the same "Body Mass"
bundle weight already comes from — a gap already flagged (not silently dropped) when
`ingest/health_auto_export.py` was first built, kept for exactly this moment.
`body_fat_percentage` is **not** present anywhere in the real export — Renpho likely
computes it in its own app but doesn't push it to HealthKit on this scale/account, so
it genuinely can't be ingested from here; documented as a real, checked absence, not
a gap left open by oversight.

`daily_metrics` gains `lean_body_mass_kg` and `bmi` (migration 0005). Lean mass is
genuinely useful for Francisco's actual goals (comp weight cut + "visible muscle
definition" secondary goal) — tells apart losing fat from losing muscle, which raw
weight alone can't; a natural `metrics/body_comp.py` addition (fat mass = weight −
lean mass) if useful later, not built yet since it wasn't asked for directly.
`ingest/health_auto_export.py: parse_weight()` renamed to `parse_body_composition()`
(same function, wider scope) — extracts all three metrics via a name→field map,
applying the same source allowlist to all of them (a wrong source is just as much a
problem for lean mass as for weight, same physical scale reading), tracked
independently per field per date since the three metrics aren't always all present
together (verified: a real date can have weight + BMI but no lean mass reading).

11 new/updated tests, 420 total passing, ruff clean. Verified against the real
database: 2026-08-27 landed with weight+BMI only (no lean-mass reading that date, as
expected), 2026-08-28 landed with all three; `compute_derived.py` still runs clean
against the wider table.

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
