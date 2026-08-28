# Recording a BJJ session with the Garmin chest strap

Practical workflow for capturing real HR/training-load data for BJJ sessions once the
Garmin chest strap (per [ADR 0002](decisions/0002-bjj-wearable-chest-strap.md)) is in
hand. This is operational guidance, not code — nothing here is built yet (Phase 6 is
where live Garmin sync lands). Written 2026-08-27 in response to Francisco's proposed
workflow: pair the strap, start "Cardio" or "HIIT" on the watch (no native BJJ profile
exists), then remove the watch and leave only the strap on.

## The proposed workflow, and the one real risk in it

Pairing the strap to the watch, starting a recording, then taking the watch off is
basically right — but the watch is what's writing the activity file, and Bluetooth/ANT+
range is roughly 3m in open air, less through bodies and mats. If the watch sits at the
edge of a mat you're rolling across, expect **connection drops during the session**,
which show up as gaps in HR data for that stretch (not invented data — per design
principle 6, a gap just stays missing — but it's still lost signal you'd rather have).

Chest straps with onboard memory (HRM 600, HRM-Pro Plus, HRM-Pro — **not** the HRM 200
or HRM-Dual, which have no storage and only broadcast live, confirmed 2026-08-27, see
[ADR 0002](decisions/0002-bjj-wearable-chest-strap.md)) buffer HR data internally and
sync it back on reconnect, which is the real fix for this — but the exact behavior (does
it *backfill gaps in an already-started watch activity*, or does it only support a
*fresh phone-only recording*?) varies by strap/watch firmware and isn't worth assuming
blind. **Test it on one low-stakes open mat class before trusting it for a whole camp
block** — start a session, deliberately walk the watch a few meters away for a few
minutes mid-roll, then check afterward whether that stretch of HR data is intact or
missing. Cheap to verify, expensive to discover mid-Block-3.

## Two ways to run it

1. **As proposed — watch starts the recording, then comes off.** Simplest if the
   buffering/backfill works as hoped. Fallback if it doesn't: keep the watch within a
   few meters (e.g. at the edge of the mat you're actually training on, not across the
   whole gym) rather than in a bag on the other side of the room.
2. **Phone-only recording via Garmin Connect Mobile.** The HRM 600 / HRM-Pro Plus line
   supports recording straight to the Connect Mobile app without a watch at all — same
   underlying range constraint applies to the phone instead of the watch, but it means
   not having to manage/protect the watch itself during rolling. Worth trying if option
   1's gaps turn out to be a real problem.
3. **Simplest fallback if neither buffers reliably in practice:** just wear the watch
   too, tucked under a rashguard sleeve or a wrist wrap. A Forerunner 165 is low-profile
   enough that this is a minor concession, not a reversal of the decision to move HR
   measurement to the chest strap for accuracy — the strap still does the actual HR
   sensing either way.

## Which activity profile: Cardio or HIIT?

Neither is a real fit (there's no BJJ profile on the 165), so this is about which gets
usable data with the least friction:

- **Cardio** — starts recording immediately, no pre-built structure required. The safe
  default.
- **HIIT** — better conceptual fit for the actual physiology (bursts of high intensity
  interspersed with lower-intensity control/transition work), *if* the watch's HIIT mode
  supports freeform/open sets (lap button between rounds) rather than requiring a
  pre-planned interval structure. Worth checking once the strap arrives.
- Garmin's Training Effect (aerobic/anaerobic) is computed from the HR stream itself
  (Firstbeat's EPOC-based model), not gated hard by activity type — so either profile
  should produce usable `aerobic_te`/`anaerobic_te` data once Phase 2/6 ingests it. Don't
  over-index on which label is "more correct" before there's real data to compare.
- **Practical test:** run one session on Cardio and one on HIIT (or the same session
  re-labeled after the fact, if Garmin Connect allows editing activity type post-hoc),
  and compare the resulting training load/TE numbers against your own session-RPE for
  that class. This is exactly the calibration step already planned in the kickoff doc
  (section 2.4) — it settles which profile to standardize on with real data instead of
  guessing now.

## Update 2026-08-28: custom "BJJ" profile, verified against a real recording

Francisco didn't go with the Cardio/HIIT recommendation above — instead created a
custom Garmin activity profile (starting from "Otros"/Other) and renamed it **"BJJ"**
on the watch. This is a real, deliberate deviation from this doc's original
recommendation, and turns out to be **arguably better**, not worse — verified by
recording a real test session and inspecting the synced data directly (never
assumed):

- `activityType.typeKey` comes through as **`"other"`** regardless of the on-device
  rename — Garmin's own type taxonomy doesn't change just because the display name
  did. `activities.sport` is `"other"` for these sessions, same as Cardio/HIIT would
  have given a similarly generic value.
- **The custom name DOES sync through** as `activityName: "BJJ"` — real, confirmed
  data, not assumed. `ingest/garmin.py` now stores this in `activities.sub_sport`
  (lowercased directly, not run through `normalize_sport_name()` — that function
  mangles a free-typed acronym like "BJJ" into `"b_j_j"`, verified directly; it's
  built for CamelCase API constants, not user-typed names) whenever `sport == "other"`
  and a name is present. So `sport="other", sub_sport="bjj"` is now a real,
  filterable signal — arguably *more* identifiable than Cardio/HIIT would have been,
  since "Cardio" is ambiguous with any other cardio work, and this project's own
  design (design principle 5's sport-family table) already treats an unmapped
  `sport` value like `"other"` as its own isolated family, so no dedup risk either.
- **Data screen configuration recommended** (2026-08-28, not yet reflected on the
  device as of this note): drop Distance/Speed (meaningless indoors), add the
  built-in "HR Zone Gauge" screen, turn off GPS/satellite search (pointless indoors,
  pure battery drain trying to acquire a lock it'll never get).

### Francisco's lap-recording plan — real, thoughtful, not yet ingested

Francisco's actual workflow: start the watch at the beginning of class (lap 1 =
drilling), then a new lap at the start of each sparring round (5 min work + 1 min
rest as one lap), and a new lap for a full rest round too (6 min) — the intent being
that HR level during a lap should make sparring-vs-rest laps distinguishable after
the fact, and round-by-round HR visible directly.

**This works today in the Garmin Connect app itself** (Garmin always shows lap
splits for a lapped activity, zero new code needed for Francisco to see it there).
**It does NOT flow into Health OS yet** — `ingest/garmin.py` only pulls whole-activity
summaries (`get_activities_by_date`), never per-lap detail. The library exposes
`get_activity_splits()` for this (confirmed present on the installed `garminconnect`
client, not yet called anywhere in this codebase) — real, scoped, buildable next step
if Francisco wants lap-level data (round HR, rest-round HR) inside Health OS itself
rather than only visible in Garmin Connect. Would need: a new table (one row per
lap — activity_id, lap_index, start_utc, duration_s, avg_hr, max_hr), new ingestion
code calling `get_activity_splits()`, and some HR-threshold-based classification to
label a lap as "sparring" vs "rest" (Garmin doesn't know this itself — Francisco's own
plan is to infer it from HR level, which means our code would have to do that
inference, not just store raw laps). Not started — flagged here so it isn't lost,
same as every other "known next step, not yet built" note in this project.

**Known accuracy caveat, unchanged from ADR 0002's original reasoning**: Francisco is
recording with the watch's own optical wrist HR (chest strap not yet in regular BJJ
use) — optical sensors are more vulnerable to motion/compression artifact than the
chest strap, especially relevant for grappling's constant grip/wrist contact. Lap-
level HR from this test will be directionally useful but not as clean as once the
strap is the actual sensor.

## Design note for Phase 1/3: link, don't dedupe

Regular activities get deduplicated across sources (Garmin > Strava > Apple Health,
design principle 5) because the *same* session might show up more than once. BJJ is
different: the chest-strap-recorded Garmin activity (real HR, training load, TE) and the
manual `bjj_sessions` log entry (session type, rounds, RPE, niggles) for the same class
are **two different views of one session**, not duplicates of each other. They should be
**linked** — the manual log row should carry the matched Garmin `activity_id` (matched
by date + rough time overlap, same as the existing dedup matching logic, just recorded
as a link rather than resolved as a merge) — so that once the strap is in regular use,
`bjj_sessions.training_load` can be taken from Garmin's real number instead of the
Foster's-method estimate, and the RPE-based calibration factor (section 2.4) gets
computed directly from paired real/estimated load on the same sessions rather than from
looser day-level correlation. Worth remembering when the schema (`core/schema.sql`) and
merge logic (`core/dedupe.py`) get built in Phases 1 and 3 — this isn't built yet, just
recorded so it isn't lost.
