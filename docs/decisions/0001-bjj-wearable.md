# 1. BJJ wearable: Garmin Cirqa over Fitbit

Date: 2026-08-27
Status: Superseded by [0002](0002-bjj-wearable-chest-strap.md)

## Context

BJJ is currently the single largest untracked training stimulus in the week — roughly
270-400 minutes of high-intensity work per week that no wearable captures (see kickoff
doc section 2.4). Until this is closed by hardware, it's closed by manual logging
(Foster's session-RPE method) as a first-class ingestion path.

The question on the table: Fitbit, or the new Garmin Cirqa, for tracking BJJ sessions.

## Decision

**Garmin Cirqa, worn on the bicep, not Fitbit.**

## Reasoning

- **Form factor fits the sport.** The Cirqa is screenless with a fabric velcro band —
  nothing to smash, snag, or crack under a rashguard or gi sleeve. This matters
  specifically for grappling in a way it wouldn't for running or lifting.
- **Placement accuracy.** Garmin explicitly supports wearing the Cirqa as an arm band.
  Upper-arm placement is materially more accurate than wrist optical HR during
  grappling, where wrist compression and hard gripping wreck the signal.
- **Zero new ingestion pipeline.** Critically, the Cirqa lands in Garmin Connect. That
  means one identity, one source of truth, and no new adapter, auth flow, or
  deduplication problem. Fitbit would mean a second cloud, a second API, a second auth
  flow, and a permanent dedup problem against Garmin — in exchange for worse training
  metrics on the mat. This is the deciding factor given the system's design principle
  of one canonical store (kickoff doc section 3, principle 3).
- **Cost.** ~$199, no subscription.

## Alternatives considered

- **Fitbit (any current model).** Rejected. Would require a second ingestion adapter,
  a second OAuth flow, and ongoing deduplication against Garmin activities (start-time
  and duration matching, source precedence — see design principle 5). Buys nothing in
  training-metric quality that offsets that permanent maintenance cost, since Garmin's
  Connect ecosystem is already the system's backbone.
- **Do nothing, keep relying on manual logging.** Viable short-term (the manual BJJ
  logger from section 2.4 covers this), but doesn't close the HR/load-during-rolling
  gap that motivated this question in the first place.
- **Chest strap (e.g. under the rashguard).** Not chosen now, but flagged below as the
  fallback if HR accuracy turns out to matter more than the Cirqa can deliver.

## Caveat

The Cirqa uses Garmin's older Elevate Gen4 optical sensor. No optical HR sensor —
wrist or bicep — is fully trustworthy during grappling; motion artifact and gripping
still degrade the signal, just less than at the wrist. If HR accuracy on the mat
turns out to matter once real data is in hand, the cheaper and better answer is a
chest strap worn under the rashguard, not a different optical wearable.

## When to revisit

Do not buy anything until Phase 3 (deduplication and canonical merge) is running and
the BJJ data gap is *provably* the bottleneck — i.e. once CTL/ATL/TSB (ADR 0003) and
readiness are computed from manual logs alone, and it's clear that missing
HR/load-during-rolling data is limiting what the coaching layer can say. Buying
hardware before then is
solving a problem that hasn't been confirmed yet.
