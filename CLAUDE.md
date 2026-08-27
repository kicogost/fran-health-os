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

**Phase 0, Phase 1, and two-thirds of Phase 2 complete as of 2026-08-27.** Strava and
Apple Health are backfilled into the real `data/health.db`; Garmin is still blocked —
Francisco requested it but it hadn't arrived (takes the platform days to generate).

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

Steps/sleep/HR are deliberately **not** ingested from Apple Health yet — the kickoff
doc's own guidance is that Apple Health only adds value for watch-not-worn movement
data and non-Garmin apps, which needs Garmin's own daily data to reconcile against
(Phase 3's job, and Garmin isn't loaded yet). Building that now would just need
reworking once Garmin lands.

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

Both backfills are idempotent (verified: re-running produced identical row counts) and
logged to `ingest_runs`. Entry point: `uv run python scripts/backfill.py [--source
strava|apple_health|garmin|all]`.

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
2. 🟡 Historical backfill — Strava ✅, Apple Health ✅, Garmin ⬜ (export not yet received).
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
pick changed. Francisco confirmed 2026-08-27 he's buying a Garmin strap.

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
  ingest/               strava_bulk.py, apple_health.py, common.py (shared helpers) — garmin.py/garmin_bulk.py not yet written
  core/                 db.py, timezones.py, dedupe.py (activities cross-source dedup, live), schema.sql (snapshot), migrations/0001_initial_schema.sql (source of truth), models.py
  metrics/              body_comp.py (weight trend + comp countdown) — baselines.py, readiness.py, load.py not yet written (wait on Garmin)
  coach/                rules.py, briefing.py, weekly_retro.py
  dashboard/             app.py (Streamlit)
scripts/                backfill.py (Phase 2 entrypoint, runs dedupe.py automatically after ingestion), log_bjj.py (manual BJJ logger), log_measurement.py (waist/tape logger), weight_report.py (Phase 4 preview) — sync.py not yet written
tests/                  core/, ingest/, metrics/, scripts/, fixtures/ (synthetic — never real personal data, fixtures are committed to git)
docs/decisions/          ADRs, one per non-obvious choice
```

## Canonical schema (target — lands in Phase 1)

Minimum tables, full column lists in kickoff doc section 5:

- **`daily_metrics`** — one row/date: weight, RHR, HRV, sleep stages/score, Body
  Battery, stress, steps, kcal, VO2max, training readiness, respiration, SpO2, skin temp.
- **`activities`** — one row/session: `source`/`source_id`, timing, sport, HR zones,
  training load, TE, power, `merged_from` (JSON of superseded rows).
- **`bjj_sessions`** — the manual log, joined into `activities` with computed load. Once
  the chest strap (ADR 0002) is in use, also carries a `linked_activity_id` pointing at
  the matching Garmin-recorded activity for that session — linked, not deduplicated
  against it; see `docs/bjj_recording_workflow.md`.
- **`subjective_log`** — one row/date: felt note, protein_hit, gassed, niggles, day_note,
  `social_meal` (correlated against weight trend — this is the known deficit disruptor).
- **`body_measurements`** — waist_cm (Sunday, fasted, below navel; baseline 86 cm) + other tape measures.
- **`derived_daily`** — every computed metric below, with the input values and window
  sizes that produced it.
- **`ingest_runs`** — audit log: source, timestamps, rows in/upserted/skipped, errors.

## Derived metrics (target — lands in Phase 4, pure functions, unit-tested against fixtures)

- **HRV baseline** — 60-day rolling median + SD. `balanced` within ±1 SD, `low`/`high`
  beyond. Needs ≥21 days before any status; below that, `insufficient_data`. Seed
  thresholds while the window fills (>90 ms green, 75-85 ms capped) are a temporary
  placeholder — switch to the computed baseline automatically at 60 days, log the
  switchover.
- **RHR baseline** — same structure. Flag a >1 SD sustained rise across 3 consecutive days.
- **ACWR** — acute = 7-day rolling load sum; chronic = 28-day rolling avg of those sums;
  ACWR = acute/chronic. Sweet spot 0.8-1.3; >1.5 = ramping too fast; <0.8 = detraining.
  Must include BJJ manual load or the number is meaningless.
- **Monotony/strain (Foster)** — monotony = mean daily load ÷ SD of daily load over 7
  days; strain = weekly load × monotony. Flag monotony >2.0.
- **Sleep debt** — rolling 14-day sum of (8.0h need − actual), reported in hours.
- **Weight trend** — never show raw daily weight as headline. 7-day EWMA + OLS slope
  over trailing 21 days (kg/week) with its confidence interval — noise is comparable to
  signal at these magnitudes.
- **Comp countdown** — EWMA weight, kg remaining, weeks remaining, required kg/week vs
  actual kg/week. Required >0.7 kg/week = red (a performance-risk problem, not a
  fat-loss problem).
- **Readiness score (0-100)** — own composite alongside Garmin's Training Readiness, so
  disagreement is visible. Weights live in `config/athlete.yaml` (tunable): 35% HRV
  deviation (SD units, clamped ±2), 25% sleep (last-night vs 8h need + 14-day debt), 15%
  RHR deviation (inverted), 15% ACWR-vs-sweet-spot, 10% subjective input. Always emit
  the component breakdown alongside the score.

## Coaching layer (target — lands in Phase 7)

**Deterministic rules first, prose second.** The rules engine produces a decision + reasons; the language layer only narrates that — it never invents a recommendation the rules didn't produce.

**Daily briefing** (morning): (1) today's session adjusted for readiness, (2) one
nutrition focus, (3) one trend observation *only if actually notable* — silence is valid,
don't manufacture an insight daily.

**Readiness bands** (against the fixed weekly shape):
- **Green ≥75** — train as scheduled; BJJ live rounds fine; lifting days get a load progression attempt.
- **Amber 55-74** — train as scheduled, cap intensity; BJJ technical/no-ego rolls; hold calisthenics load; bike strictly Z2.
- **Red <55** — downgrade, don't delete: BJJ → drilling only; calisthenics → mobility + light kettlebell. Never prescribe a full rest day off one bad number — require 2 consecutive red days or 3 amber days first.
- **Structural triggers** — 3 consecutive days HRV < baseline−1SD, or ACWR >1.5 for 4 days, or monotony >2.0 with strain in the last-8-weeks top quartile → formal capped-week/deload recommendation. Deloads are already ~every 4 weeks on the calendar — flag when calendar and data disagree.

**Hard safety rails (in the rules engine, not just prose):** never recommend running;
never increase pressing/overhead load in a week with a logged neck niggle; never a
deficit deeper than 2,300 kcal implies, never fasting, never "making up" for a social
meal; never add a 4th/5th hard session — the architecture is fixed.

**Weekly retro** (Sunday): 7-day weight trend + CI, sessions completed vs planned, total
load with ACWR/monotony, sleep totals, protein adherence rate, social-meal count
correlated against weight trend, waist delta, proposed calisthenics progression.

**Correlation engine** (last, needs 90 days of data): Spearman rho with n and p between
candidate inputs (sleep, deep sleep, social meals, steps, BJJ load, gi/no-gi) and
outcomes (next-day HRV/readiness, weekly weight slope, gassed rate). n<30 = provisional.
Never present correlation as causal. Top 3 findings max.

## Dashboard (target — lands in Phase 5)

Streamlit, Plotly, dark theme, raw points always shown behind smoothed lines (lighter
shade). Pages: **Today** (readiness + breakdown, prescription, sleep, weight EWMA, comp
countdown) · **Trends** (weight/HRV/RHR/sleep stages, 30/90/365-day windows) ·
**Training** (load by day/sport, ACWR gauge, monotony, calisthenics progression) ·
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
