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
