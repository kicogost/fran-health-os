# 2. BJJ wearable, revised: Garmin chest strap over the Cirqa

Date: 2026-08-27 (model pick updated 2026-08-27 after checking current lineup)
Status: Accepted
Supersedes: [0001](0001-bjj-wearable.md)

## Context

[ADR 0001](0001-bjj-wearable.md) picked the Garmin Cirqa (bicep-worn, screenless) over
Fitbit, optimizing for discretion and ecosystem fit, but flagged a caveat: it still uses
an optical (PPG) sensor, and "no optical HR sensor — wrist or bicep — is fully
trustworthy during grappling." That ADR named a chest strap as the fallback "if HR
accuracy on the mat turns out to matter."

Francisco then asked directly: what's the best wearable for BJJ that's discreet *and*
measures HR as correctly as possible — accuracy stated as the explicit priority, not
just a nice-to-have. That changes the answer.

## Decision

**A Garmin chest strap with onboard memory, worn under the rashguard/gi, not the
Cirqa — specifically the HRM 600 (current flagship), with the HRM-Pro Plus as a valid
cheaper alternative.** See "Which specific model" below — this matters more than it
first looks, because not all Garmin straps have onboard memory, and the whole
watch-off-mid-roll recording workflow depends on the strap having it.

## Reasoning

- **Measurement principle, not just placement, is the accuracy limiter.** The Cirqa's
  bicep placement was an improvement over wrist because it's harder to compress and
  further from where hands grip — but it's still a PPG (optical, blood-flow) sensor,
  and PPG is inherently vulnerable to motion artifact and any compression near the
  sensor. A chest strap reads the heart's electrical activity directly (ECG), which is
  immune to that failure mode entirely — this is why chest straps are used as the
  *ground truth* against which optical sensors get validated in accuracy studies, not
  just a "better" optical alternative. For a sport that is constant compression, grips,
  and motion, that's the deciding difference once accuracy is the stated priority.
- **Still zero new ingestion pipeline.** A memory-equipped Garmin strap (HRM 600 /
  HRM-Pro Plus) has onboard storage and broadcasts to the Garmin Connect Mobile app
  directly — it can record a full session without the watch being worn at all, then
  sync into Garmin Connect afterward. If the Forerunner 165 is worn and recording, it
  works the same way any external Garmin HR sensor does. Either path lands in Garmin
  Connect exactly like the Cirqa would — no change to design principle 3 (one canonical
  store) or to the ingestion adapter design.
- **Equal or better on discretion.** Fully hidden under a rashguard, no screen, and
  unlike the Cirqa (or the watch itself), there's nothing at the wrist or bicep to catch
  a grip, gi sleeve, or finger during scrambles — arguably the single biggest practical
  win, since a wrist-worn watch is itself a minor snag/injury risk in grappling that the
  Cirqa only partially solved by moving to the arm.
- **Cheaper.** ~$130 vs. the Cirqa's ~$199, still no subscription.

## Which specific Garmin strap: onboard memory is the deciding spec

Checked the current lineup (2026-08-27) because this directly determines whether the
"pair strap → start activity → take watch off" workflow (see
`docs/bjj_recording_workflow.md`) works at all:

| Model | Onboard memory (records without a nearby device)? | Notes |
|---|---|---|
| **HRM 200** (current entry-level, replaces HRM-Dual) | **No.** Broadcasts live only — needs a continuously-connected watch or phone the whole session. | Wrong pick for this use case — the whole point is surviving Bluetooth range drops mid-roll. |
| **HRM-Dual** (older entry-level, being phased out) | **No**, same limitation as HRM 200. | Same disqualifier. |
| **HRM-Pro Plus** (previous flagship, still sold ~$130) | **Yes** — ~18h onboard storage, syncs on reconnect. | Fixed, non-detachable sensor pod (hand-wash only); ~12-month coin-cell battery (nothing to charge). |
| **HRM 600** (current flagship, launched May 2025, ~$170) | **Yes** — onboard memory, standalone activity recording, plus HRV during the session. | Detachable pod, **machine-washable strap** — genuinely relevant for a sweat-heavy contact sport, given the hygiene notes already in the comp-prep plan (skin checks, washing rashguards after every session). Rechargeable, ~2 months per charge at ~1h/day use — BJJ's 4 mat sessions/week at up to 2h (Friday open mat) will draw that down faster, so expect closer to monthly charging, not a big deal but worth knowing going in. |

**Recommendation: HRM 600**, primarily for the washable strap — a fixed pod you can
only hand-wash is a real downgrade for a sport with this much sweat and skin contact,
and Garmin has explicitly positioned the HRM 600 as the HRM-Pro Plus's replacement, so
it's the strap that'll get ongoing firmware support. **HRM-Pro Plus remains a
perfectly good, cheaper (~$40 less) alternative** if the coin-cell battery (no charging
cadence to manage) matters more than the washable pod — it has the same onboard-memory
capability this whole workflow depends on. Do not buy the HRM-Dual or HRM 200 — neither
has onboard memory, so taking the watch off mid-roll would just mean data loss, not a
buffered gap.

Sources: [Garmin HRM-Pro Plus owner's manual](https://www8.garmin.com/manuals/webhelp/GUID-57B75051-8E96-44B8-A89E-470B3E3BCD32/EN-US/GUID-DA3DAF11-E2D1-4F88-A102-097E094C4B7B.html), [Garmin HRM 600 press release](https://www.garmin.com/en-US/newsroom/press-release/sports-fitness/garmin-unveils-the-hrm-600-heart-rate-monitor-with-more-ways-to-capture-and-improve-training/), [Garmin Rumors: HRM 600 replaces HRM-Pro Plus](https://garminrumors.com/garmin-hrm-600-replaces-hrm-pro-plus-with-big-upgrades/), [Garmin HRM 200 vs HRM-Pro Plus vs HRM 600 buyer's guide](https://hmmuller.com/garmin-hrm-200-vs-hrm-pro-plus-vs-hrm-600/), [Garmin Forums: HRM-Dual use without watch nearby](https://forums.garmin.com/sports-fitness/running-multisport/f/accessories-sensors/346132/hrm-dual-use-without-watch-nearby).

## Alternatives considered

- **Garmin Cirqa (the 0001 pick).** Superseded — see Reasoning. Still a reasonable
  choice if screenless bicep wear mattered for reasons beyond HR accuracy (e.g. sleep
  tracking or Body Battery from a second wear location), but that wasn't the ask.
- **Polar H10.** The most independently validated consumer chest strap in accuracy
  studies — arguably even better-validated than Garmin's own strap — and cheaper still
  (~$90). Not the top pick only because it doesn't write to Garmin Connect on its own;
  it would need to pair to the Forerunner 165 as an external ANT+/BLE sensor during a
  recorded activity to land in Garmin Connect the same way, which works fine but means
  the watch has to be worn and recording (reintroducing the wrist-snag question) rather
  than the strap-alone, watch-free recording a memory-equipped Garmin strap offers.
  Worth switching to if the Garmin strap's accuracy or durability disappoints in
  practice.
- **Wrist optical (status quo, wearing only the Forerunner 165).** Rejected outright for
  BJJ specifically — this is the case the Cirqa was already chosen over.

## Caveats

- Chest straps need skin contact to read well; a bone-dry strap at the very start of a
  session can under-read for the first minute or two. Not a real issue in BJJ
  specifically — warm-up sweat resolves it fast, and a quick wet-down before rolling
  avoids it entirely.
- Under heavy top pressure (mount, side control) the strap can be uncomfortable, and on
  long sweaty sessions it can migrate. Standard combat-sport experience with chest
  straps is that this is manageable with a snug fit positioned just below the sternum,
  not a reason to prefer optical.

## When to revisit

Unchanged from 0001: don't buy anything until Phase 3 is running and the BJJ data gap
is *provably* the bottleneck. This ADR only changes *which* device to buy when that
point is reached, not whether or when to buy it.
