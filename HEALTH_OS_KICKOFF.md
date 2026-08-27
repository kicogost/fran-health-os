# Health OS: kickoff prompt

**How to use this file.** Create an empty folder, run `git init`, drop this file in as
`HEALTH_OS_KICKOFF.md`, open Claude Code in that folder, and paste the whole thing as your
first message. Claude will scaffold the repo, then rewrite the durable parts of this
document into `CLAUDE.md` so every future session starts with the same context.

Everything below the line is the prompt.

---

## 0. Role

You are the engineer and analyst building my personal health operating system. This is a
local-first data warehouse plus coaching layer, built on my own wearable data. Think Whoop,
except I own the database, I set the rules, and the rules are tuned for a jiu jitsu
competitor rather than a generic fitness consumer.

You are not writing a product for other users. There is exactly one user. Optimise for
correctness, transparency, and my ability to read the code six months from now. Do not
optimise for scale, generality, or configurability.

## 1. Athlete profile

| Field | Value |
|---|---|
| Name | Francisco |
| Age | 24 |
| Height | 176 cm |
| Current weight | ~79 kg (plateaued in the 79 to 79.8 band since mid July 2026) |
| Location | Portals Nous, Mallorca |
| Timezone | Europe/Madrid (handle DST correctly) |
| Units | Metric throughout. kg, km, °C, ml |
| Week starts | Monday |

**Primary near-term goal:** no-gi BJJ competition in October 2026 at the -77.27 kg division.
Weight must be at or under 77.27 kg on the morning of the comp, with performance intact.

**Secondary goal:** visible muscle definition, better mat conditioning.

**Fixed weekly architecture.** The coaching layer advises within this shape. It does not
redesign it.

- Mobility: 15 min daily, pre-breakfast
- BJJ: Mon, Wed, Fri at 18:00. Friday is open mat, 2 hrs
- Gi drilling: Tue evenings, technique only
- Calisthenics: Tue and Thu mornings, 45 min. Tue is push and lower, Thu is pull and posterior
- Bike: Saturday 07:30, 1.5 to 2 hrs easy Z2
- Sunday: rest or active recovery, plus weekly retro
- Dinner at 21:00

**Nutrition guardrails.** The coaching layer must respect these and never violate them:

- 180 g protein daily is the one hard number. Everything else is the plate framework
- ~2,300 kcal target, roughly a 500 kcal deficit
- Never recommend calorie obsession, fasting, extreme deficits, or "speed up" tactics
- No alcohol, 2 black coffees daily
- Saturday restaurant dinner is allowed and planned for
- Known constraint: social meals are the primary deficit disruptor. Deficit compliance,
  not programming, is the binding constraint

**Equipment:** pull-up bar (outdoor terrace), 12 kg kettlebell, 10 kg barbell with 50 kg of
plates, adjustable bench.

**Injury history to encode as guardrails:** prior right knee injury from running (running is
off the menu permanently), and a recurring neck vulnerability aggravated by forward head
position under load.

## 2. Data sources and their actual constraints

Read this section carefully before writing any ingestion code. Most of the difficulty in
this project is here, not in the analysis.

### 2.1 Garmin Forerunner 165 (primary source of truth)

Everything wearable-derived comes from Garmin: sleep stages, overnight HRV, resting heart
rate, Body Battery, stress, VO2max estimate, training load, training readiness, activity
records, steps.

Reality check on access:

- Garmin has **no official free personal API**. The Health API and Activity API are B2B
  partner programs and are not realistically available to an individual.
- The working route is the **unofficial Garmin Connect client**: the `garminconnect` Python
  package (which sits on top of `garth` for SSO auth and token caching). It works, and it
  breaks occasionally when Garmin changes their login flow. Design for that: wrap all
  Garmin calls behind one adapter module so a breakage is a one-file fix.
- If my Garmin account has MFA enabled, the login flow needs an interactive prompt on first
  auth. Cache the resulting `garth` session tokens to disk so subsequent runs are headless.
- For the **historical backfill**, do not scrape years of data through the unofficial
  client. Instead I will request the official bulk export from Garmin's Account Management
  Center ("Export Your Data"). It arrives as a large zip of JSON and FIT files and takes
  days to be generated. Write a parser for that zip. Verify the actual folder structure
  from my real export rather than assuming it.
- Consider `garmindb` (the open source tool that syncs Connect data into SQLite and parses
  FIT files) as either a dependency or a reference implementation. Evaluate it and tell me
  which way you want to go, with reasoning.
- For per-activity detail, FIT files are the richest source. Use `fitdecode` or `fitparse`.

### 2.2 Apple Health (iPhone)

Important: Garmin Connect already syncs into Apple Health, so **most of Apple Health is a
duplicate of Garmin data, often with worse fidelity**. Do not treat these as two independent
sources. Apple Health earns its place for two things only:

1. Step and movement data captured when I am not wearing the watch (phone in pocket)
2. Data from any third-party app that writes to HealthKit and does not write to Garmin

Access:

- One-time export: Health app, tap profile picture, "Export All Health Data". Produces
  `export.zip` containing a very large `export.xml`. Parse it with a streaming XML parser
  (`lxml.etree.iterparse`), never `ElementTree.parse`, or it will eat all available RAM.
- Ongoing automation: the **Health Auto Export** iOS app can push JSON or CSV to a local
  REST endpoint, iCloud Drive, or Dropbox on a schedule. This is the pragmatic sync path.
  Set up the folder drop first, REST later if I want it.
- Every HealthKit record carries a source device. Use it to filter out Garmin-originated
  records at ingest time.

### 2.3 Strava

- Official API, free, works fine for personal use. Create a personal API application at
  the Strava developer settings page, do the OAuth dance once, store the refresh token.
  `stravalib` handles the token refresh cycle well.
- Rate limits are modest and change from time to time. Look up the current published limits
  rather than trusting a number I give you, then implement backoff that respects them.
- Same duplication warning: Garmin auto-uploads to Strava, so recent rides are duplicates.
  Strava's real value is **historical depth**, specifically biking and running data from
  before I owned the Forerunner 165.
- For the backfill, use Strava's bulk archive export (Settings, My Account, Download or
  Delete Your Account, Request your archive) rather than paging the API through years of
  activities.

### 2.4 BJJ (the gap)

Currently untracked, and it is the single largest training stimulus in my week. Roughly 270
to 400 minutes per week of high intensity work that the system is blind to.

Until hardware fixes this, build a **manual BJJ logger** as a first-class ingestion path,
not an afterthought. CLI entry, and a form in the dashboard. Fields:

`date, session_type (class | open_mat | gi_drilling), duration_min, rounds_rolled,
session_rpe (1-10), gassed (bool), niggles (free text), notes`

Convert manual sessions into a training load figure using session RPE (Foster's method:
`load = duration_min × session_rpe`), then calibrate the scaling factor against Garmin's
training load values on days where both exist, so BJJ load lives on the same axis as
everything else. Store the calibration factor explicitly in config so I can see and adjust it.

### 2.5 Hardware decision (answer this in Phase 0, then move on)

My question was Fitbit versus the new Garmin Cirqa for BJJ tracking. Your recommendation,
which you should record in `docs/decisions/0001-bjj-wearable.md`:

**Garmin Cirqa, worn on the bicep, not Fitbit.** Reasons: it is screenless with a fabric
velcro band, so nothing to smash or snag under a rashguard or gi sleeve; Garmin explicitly
supports wearing it as an arm band, and upper-arm placement is materially more accurate than
wrist optical HR during grappling, where wrist compression and hard gripping wreck the
signal; and critically **it lands in Garmin Connect**, which means zero new ingestion
pipeline, one identity, one source of truth. Fitbit would mean a second cloud, a second API,
a second auth flow, and a permanent deduplication problem, in exchange for worse training
metrics. It runs about $199 with no subscription.

Caveat to note in the ADR: it uses Garmin's older Elevate Gen4 optical sensor, and no
optical HR is trustworthy during grappling. If HR accuracy on the mat turns out to matter,
the cheaper and better answer is a chest strap under the rashguard. Do not buy anything
until Phase 3 is running and the data gap is provably the bottleneck.

## 3. Design principles (non-negotiable)

1. **Local-first.** Everything runs on my machine. No cloud services, no hosted database, no
   telemetry. The only outbound traffic is to Garmin, Strava, and package registries.
2. **Raw data is immutable.** Anything downloaded lands in `data/raw/` and is never edited or
   deleted by code. All transformation is reproducible from raw.
3. **One canonical store.** A single SQLite file, `data/health.db`. Every query, chart, and
   coaching decision reads from it. No parallel CSVs of record.
4. **Idempotent ingestion.** Re-running any sync must produce the same database state. Upsert
   on natural keys, never blind insert.
5. **Explicit deduplication.** Every activity row carries `source` and `source_id`. Precedence
   is Garmin, then Strava, then Apple Health. Match candidates on start time within 120 s,
   duration within 60 s, and same sport family. Log every merge decision to a table I can audit.
6. **Never invent data.** No silent interpolation, no filling gaps with averages. If a day is
   missing, it is `NULL` and it is visibly missing on the dashboard. Any derived value computed
   from partial inputs carries a `confidence` or `n_days` column.
7. **Timezone-aware everywhere.** Store UTC in the database, render Europe/Madrid. Sleep
   sessions spanning midnight are attributed to the wake date.
8. **Secrets in `.env`, never committed.** Ship `.env.example`. Add a pre-commit hook that
   blocks any commit containing a credential-shaped string.
9. **Every derived number is traceable.** If the dashboard shows a readiness score of 68, I
   must be able to click through, or run one command, and see the inputs and the arithmetic.
   No black box scores.

## 4. Repo structure

```
health-os/
  CLAUDE.md                  # you write this in Phase 0
  README.md
  pyproject.toml
  .env.example
  config/
    athlete.yaml             # profile, goals, thresholds, training architecture
    sources.yaml             # per-source settings and precedence
  data/
    raw/                     # gitignored, immutable
      garmin/{bulk_export,daily}/
      apple_health/
      strava/
    health.db                # gitignored
  src/health_os/
    ingest/
      garmin.py
      garmin_bulk.py
      apple_health.py
      strava.py
      bjj_manual.py
    core/
      db.py
      schema.sql
      dedupe.py
      models.py
    metrics/
      baselines.py
      readiness.py
      load.py
      body_comp.py
    coach/
      rules.py
      briefing.py
      weekly_retro.py
    dashboard/
      app.py
  scripts/
    sync.py                  # single entrypoint: sync all sources, recompute, report
    backfill.py
    log_bjj.py
  tests/
  docs/decisions/            # ADRs, one per significant choice
```

## 5. Canonical schema

Design the full DDL in `schema.sql`. Minimum tables:

- **`daily_metrics`** grain: one row per calendar date. Columns: date, weight_kg,
  resting_hr, hrv_overnight_ms, hrv_status (Garmin's own), sleep_total_min, sleep_deep_min,
  sleep_rem_min, sleep_light_min, sleep_awake_min, sleep_score, body_battery_max,
  body_battery_min, stress_avg, steps, active_kcal, total_kcal, vo2max, training_readiness,
  respiration_avg, spo2_avg, skin_temp_delta.
- **`activities`** grain: one row per session. Columns: activity_id, source, source_id,
  start_utc, local_date, sport, sub_sport, duration_s, distance_m, avg_hr, max_hr,
  hr_zone_1..5_s, training_load, aerobic_te, anaerobic_te, avg_power, elevation_gain_m,
  perceived_rpe, merged_from (JSON of superseded source rows).
- **`bjj_sessions`** the manual log described in 2.4, joined into `activities` with a
  computed load.
- **`subjective_log`** grain: one row per date. Columns: date, felt_note, protein_hit (bool),
  gassed (bool), niggles, day_note, social_meal (bool). This last flag matters: it is the
  known deficit disruptor and I want it correlated against the weight trend.
- **`body_measurements`** date, waist_cm (measured Sunday, fasted, below navel), plus any
  other tape measurements. Baseline waist is 86 cm.
- **`derived_daily`** every computed metric from section 6, with the input values and window
  sizes that produced it.
- **`ingest_runs`** audit log: source, started_at, finished_at, rows_in, rows_upserted,
  rows_skipped, errors.

## 6. Derived metrics (specify the maths, do not hand-wave)

Implement each of these as a pure function with unit tests against hand-computed fixtures.

**HRV baseline.** Rolling 60-day median of overnight HRV plus the standard deviation of that
window. Status is `balanced` inside ±1 SD, `low` below -1 SD, `high` above +1 SD. Require at
least 21 days of data before emitting a status; below that, emit `insufficient_data`.
Seed value while the window fills: I have been using above 90 ms as green and 75 to 85 ms as
capped. Treat those as a temporary placeholder and switch to the computed baseline
automatically once 60 days exist. Log the switchover.

**Resting HR baseline.** Same structure, 60-day rolling median and SD. A sustained rise of
more than 1 SD across 3 consecutive days is a flag.

**Acute:chronic workload ratio.** Acute is the 7-day rolling sum of training load. Chronic is
the 28-day rolling average of the 7-day sums. ACWR is acute divided by chronic. Sweet spot
0.8 to 1.3. Flag above 1.5 as ramping too fast and below 0.8 as detraining. BJJ manual load
must be included, otherwise this number is meaningless.

**Training monotony and strain (Foster).** Monotony is the mean daily load over 7 days
divided by the SD of daily load over the same 7 days. Strain is weekly load times monotony.
Flag monotony above 2.0: it means the week has no real hard/easy contrast, which is the
classic pattern before things go wrong.

**Sleep debt.** Rolling 14-day sum of (need minus actual), where need is 8.0 h. Report in
hours, not a score.

**Weight trend.** Never show a raw daily weight as the headline. Show a 7-day exponentially
weighted moving average, plus the slope of an ordinary least squares fit over the trailing 21
days expressed in kg per week. Compute and surface the confidence interval on that slope,
because at these magnitudes the noise is comparable to the signal.

**Comp countdown.** Given the October comp date and the 77.27 kg limit: current EWMA weight,
kg remaining, weeks remaining, required kg/week, and current actual kg/week. If required
exceeds 0.7 kg/week, mark it red, because past that point the cut stops being a fat loss
problem and starts being a performance problem.

**Readiness score (0-100).** My own composite, computed alongside Garmin's Training Readiness
so I can see where they disagree. Weights, all of which live in `config/athlete.yaml` so I
can tune them:

- 35% HRV deviation from baseline, in SD units, clamped to ±2
- 25% sleep, combining last night's duration against 8 h need and the 14-day sleep debt
- 15% resting HR deviation from baseline, inverted
- 15% ACWR positioned against the 0.8 to 1.3 sweet spot
- 10% subjective input from `subjective_log`

Emit the component breakdown alongside the score, always. A score with no breakdown is a
number I will stop trusting within two weeks.

## 7. Coaching layer

Deterministic rules first, prose second. The rules engine produces a decision and a set of
reasons; only then does the language layer turn it into a briefing. Never let the prose
invent a recommendation the rules did not produce.

**Daily briefing**, generated each morning, three parts matching how I already work:

1. Today's session, adjusted for readiness (see the bands below)
2. One nutrition focus for the day
3. One observation about the trend, and only if something is actually notable. Silence is a
   valid output. Do not manufacture an insight every single day.

**Readiness bands and prescriptions**, expressed against my fixed weekly shape:

- **Green, 75 and above.** Train as scheduled. If it is a BJJ day, live rounds are fine. If
  it is a lifting day, this is where a load progression gets attempted.
- **Amber, 55 to 74.** Train as scheduled, cap the intensity. BJJ: technical rolls, pick your
  partners, no ego. Calisthenics: hold last week's load, do not add. Bike: strictly Z2.
- **Red, below 55.** Downgrade, do not delete. BJJ becomes drilling only. Calisthenics becomes
  mobility plus a light kettlebell circuit. Never prescribe a full rest day off the back of
  one bad number; require two consecutive red days, or three amber days, before that.
- **Structural triggers.** Three consecutive days of HRV below baseline minus 1 SD, or ACWR
  above 1.5 for four days, or monotony above 2.0 with strain in the top quartile of the last
  8 weeks, triggers a formal recommendation of a capped week or a deload. Deloads are already
  scheduled roughly every 4 weeks. The engine should flag when the calendar and the data
  disagree.

**Hard safety rails encoded in the rules, not just in prose:**

- Never recommend running. Knee.
- Never recommend increasing load on pressing or overhead work in a week where neck niggles
  were logged.
- Never recommend a deficit deeper than 2,300 kcal implies, never recommend fasting, never
  recommend "making up" for a social meal with extra training or skipped meals.
- Never recommend adding a fourth or fifth hard session. The architecture is fixed.

**Weekly retro**, generated Sunday: 7-day weight trend with the slope and its confidence
interval, sessions completed versus planned, total load with the ACWR and monotony picture,
sleep totals, protein adherence rate, social meal count correlated against the weight trend,
waist measurement delta, and a proposed calisthenics progression for the coming week.

**Correlation engine**, deliberately last. Once there are 90 days of data, run simple
correlations between candidate inputs (sleep duration, deep sleep, social meals, step count,
BJJ load, gi versus no-gi) and outcomes (next-day HRV, next-day readiness, weekly weight
slope, gassed rate). Report Spearman rho with n and p, and label anything with n below 30 as
provisional. Do not present a correlation as causal. Do not report more than the top three
findings, or I will pattern-match on noise.

## 8. Dashboard

Streamlit, running locally via `streamlit run`. It is a personal tool, so speed of iteration
beats framework purity.

Pages:

1. **Today.** Readiness with its component breakdown, today's prescription, last night's
   sleep, weight EWMA, and the comp countdown.
2. **Trends.** Weight with the EWMA and trend line, HRV against its baseline band, resting HR,
   sleep stages stacked, all with selectable 30/90/365-day windows.
3. **Training.** Load by day coloured by sport, ACWR gauge, monotony, weekly volume by
   discipline, and the calisthenics progression table with working loads.
4. **Comp prep.** Weight trajectory against the required line to make 77.27 kg, with the
   projected finish and its uncertainty band.
5. **Log.** Forms for the BJJ session, subjective inputs, and the Sunday waist measurement.
6. **Data health.** Freshness per source, missing days, dedupe decisions, last ingest run.
   This page is not optional. When the pipeline silently breaks, this is how I find out.

Charts: Plotly. Dark theme. Always show the raw points behind a smoothed line, in a lighter
shade, so I can see the noise I am smoothing over.

## 9. Build phases

Do these in order. Stop at the end of each and show me what you built before continuing. Do
not run ahead.

- **Phase 0.** Scaffold the repo, `pyproject.toml`, `.env.example`, `config/athlete.yaml`
  populated from section 1, `CLAUDE.md` written for future sessions, and the ADR from 2.5.
  No data code yet.
- **Phase 1.** Schema and database layer. DDL, migrations, the upsert helpers, the audit
  tables. Tested against fixtures. Still no network calls.
- **Phase 2.** Historical backfill from the three bulk exports (Garmin zip, Apple Health
  `export.xml`, Strava archive). This is where the data actually arrives. Expect the parsing
  to be uglier than the docs suggest.
- **Phase 3.** Deduplication and the canonical merge. At the end of this phase I should have
  one clean row per day and one clean row per activity across all of history.
- **Phase 4.** Derived metrics from section 6, with unit tests.
- **Phase 5.** Dashboard. Read-only first, then the logging forms.
- **Phase 6.** Live incremental sync via the unofficial Garmin client and the Strava API,
  plus `scripts/sync.py` as the single daily entrypoint.
- **Phase 7.** Coaching rules and the briefing generator.
- **Phase 8.** Scheduling (launchd or cron), and correlation analysis once the data depth
  justifies it.

## 10. Working agreement

- Python 3.12 or newer. `uv` for dependency management. `ruff` for lint and format. `pytest`
  for tests. Type hints on every public function.
- Ask before adding any dependency beyond the ones named in this document, and say what it
  buys us.
- Small commits, conventional commit messages, one logical change each.
- Tests are mandatory on the ingest and metrics layers. The dashboard can go untested.
- Any non-obvious choice gets an ADR in `docs/decisions/`, numbered, with the alternatives
  considered.
- If something in this brief is wrong, out of date, or a bad idea, say so before building it.
  I would rather be corrected in Phase 0 than debug my own bad spec in Phase 6.
- When an external API or library behaves differently from what this document describes,
  trust the API and update the document.

## 11. Definition of done for v1

Every morning I run one command. It syncs Garmin and Strava, recomputes everything, and
prints a briefing to the terminal: readiness with its components, today's prescribed session,
one nutrition focus, and any trend worth mentioning. The dashboard is one command away for
when I want to dig. The BJJ gap is closed by manual logging until hardware closes it properly.
Nothing in the system ever shows me a number I cannot trace back to its inputs.

## 12. Out of scope

No multi-user support. No authentication. No hosting or deployment. No mobile app. No
Docker unless a dependency forces it. No LLM calls inside the metrics layer, ever, since
derived numbers must be deterministic and reproducible. Language generation happens only in
the briefing layer, and only from rules-engine output.
