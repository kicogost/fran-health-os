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

**Phase 0 complete** (repo scaffold, config, this file, ADR 0001). No data code exists
yet — no schema, no ingestion, no metrics, no dashboard. Next up: **Phase 1**, the
SQLite schema and database layer (DDL, upsert helpers, audit tables), tested against
fixtures, still with zero network calls.

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
1. ⬜ Schema + DB layer (`core/db.py`, `core/schema.sql`, upsert helpers, `ingest_runs` audit table).
2. ⬜ Historical backfill from the three bulk exports (Garmin zip, Apple Health `export.xml`, Strava archive).
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
  sources.yaml         (not yet created — per-source settings/precedence, lands with ingestion)
data/
  raw/                 immutable per-source downloads (gitignored)
  health.db             the one canonical store (gitignored)
src/health_os/
  ingest/               garmin.py, garmin_bulk.py, apple_health.py, strava.py, bjj_manual.py
  core/                 db.py, schema.sql, dedupe.py, models.py
  metrics/              baselines.py, readiness.py, load.py, body_comp.py
  coach/                rules.py, briefing.py, weekly_retro.py
  dashboard/             app.py (Streamlit)
scripts/                sync.py (single daily entrypoint), backfill.py, log_bjj.py
tests/
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
