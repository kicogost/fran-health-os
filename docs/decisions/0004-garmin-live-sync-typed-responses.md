# 4. Garmin live sync: use `garminconnect[typed]`'s validated response models

Date: 2026-08-28
Status: Accepted

## Context

Phase 6 (kickoff doc section 9) calls for live incremental sync via the unofficial
`garminconnect` + `garth` client, wrapped behind one adapter module. Every other
ingester in this codebase (`strava_bulk.py`, `apple_health.py`, `garmin_bulk.py`) was
built only after inspecting real export files and hand-writing a parser against their
actual (often undocumented, sometimes wrong-unit) shape — see `garmin_bulk.py`'s
elevationGain history for why that discipline exists.

The live Garmin API has no bulk export file to inspect up front, and we don't yet have
Francisco's credentials to hit it directly. Reading the actually-installed
`garminconnect` package (v0.3.11) turned up `garminconnect/typed.py`: an optional
`typed` extra exposing Pydantic `BaseModel`s for a curated set of endpoints
(`get_stats`, `get_sleep_data`, `get_hrv_data`, `get_training_readiness`,
`get_activities_by_date`, `get_body_battery`), with every field's JSON alias given
explicitly and — critically — most field names on the wellness endpoints self-document
their units (`total_distance_meters`, `sleeping_seconds`, `body_battery_highest_value`),
unlike the bulk export's bare `distance`/`elevationGain`.

## Decision

**Use `client.typed.get_stats`/`get_sleep_data`/`get_hrv_data`/`get_training_readiness`
(validated Pydantic models) instead of hand-parsing the raw dicts these endpoints
return, for `ingest/garmin.py`'s daily wellness fetch.** A per-endpoint
`GarminConnectResponseValidationError` (raised when a real response fails the model's
validation) is caught and that endpoint's fields are skipped for that date — recorded
into `ingest_runs.errors`, never silently invented, never crashing the rest of the sync.

**Live activities are a partial exception.** `typed.Activity` exists and is used for
its verified field *names* (`activity_training_load`, `elevation_gain`, ...), but its
`distance`/`duration`/`elevation_gain` fields carry no unit suffix the way the wellness
models do. We assume the standard Garmin Connect REST convention (seconds, meters) —
document that assumption prominently in `ingest/garmin.py`'s module docstring — and
have `scripts/sync.py` print each newly-synced activity's converted numbers so a wrong
guess is visible on the very first real run, rather than pre-verifying it the way every
other parser's units were pre-verified (there's no bulk file to check it against ahead
of time). Two live-only fields with no verified counterpart at all —
`hrTimeInZone_0..6` and `workoutRpe`, both present on the bulk export — are left NULL
rather than guessed at, since `typed.Activity` doesn't model them and we have no
evidence the live endpoint carries them the same way.

## Reasoning

- This is arguably a *stronger* form of "verify real structure before writing a
  parser," not a departure from it: instead of us guessing field names from a sample
  file, a maintained library fails loudly (`GarminConnectResponseValidationError`,
  with `.raw` preserved) the moment Garmin's actual response stops matching the
  modeled shape — closer to a live contract test than our own hand-parsing ever was.
- `extra="allow"` on every model means Garmin adding a field never breaks us; only a
  field disappearing or changing type would raise, which is exactly the failure we'd
  want surfaced.
- `pydantic` was already an installed transitive dependency (via `garth` and
  `stravalib`); depending on it directly for this costs nothing new to install.
- The library documents this surface as "Experimental — shapes may change between
  minor releases" of *garminconnect itself* — a controlled, version-pinned risk
  (`garminconnect[typed]>=0.3.11` in `pyproject.toml`), not the same kind of risk as
  Garmin's live API changing under us either way.

## Alternatives considered

- **Hand-parse raw dicts for every endpoint, matching `garmin_bulk.py`'s style
  exactly.** Rejected: strictly more code, more chances to typo a key name, and no
  loud failure mode on drift — a renamed key would just silently read as `None`
  forever, which is precisely what design principle 9 (never invent, never
  silently miss) argues against.
- **Wait for real API access before writing anything.** Rejected: the typed models
  are themselves a form of verified ground truth (sourced from the library's own
  schema work), strong enough to build and unit-test the mapping logic against now;
  the one place real verification is still pending (live-activity units) is called
  out explicitly rather than blocking all of Phase 6 on it.

## Consequences

- `pyproject.toml`: `garminconnect>=0.2.20` → `garminconnect[typed]>=0.3.11`,
  `pydantic>=2.0` added as a direct dependency.
- `ingest/garmin.py` (new) implements this; `tests/ingest/test_garmin.py` (new, 19
  tests) exercises it against a fake `Garmin`/`typed` client — never the real API.
- `hr_zone_*_s` and `perceived_rpe` are a known gap for live-synced activities until a
  real response can be inspected and the fields added properly (or confirmed absent).
- **Live-activity unit assumption (seconds/meters) confirmed correct, 2026-08-28.**
  The first sync window happened to catch zero activities (investigated and confirmed
  as a real gap — Francisco's last Garmin activity was 4 days back, outside the
  default 3-day window, not a bug — cross-checked via `get_last_activity()`). Running
  a wider window pulled in 4 real activities with plausible numbers: a strength
  session at 1902s (31.7 min), and three rides at 51.21km/50.16km/42.76km over
  134-145 min (18.5-22.9 km/h). Elevation gain also checked out — 630m on one ride
  matches the exact figure `garmin_bulk.py`'s elevationGain cross-check found for
  what's very likely the same recurring route.
- **New finding: `activity_training_load` is also permanently NULL, contradicting
  this ADR's earlier expectation.** All 4 real activities above came back with
  `training_load = NULL`, even though `aerobic_te`/`anaerobic_te` mapped correctly
  from the same API object (ruling out a parsing bug). Almost certainly the same
  Forerunner 165 device-tier gap as `training_readiness`, though not independently
  re-verified against the raw API the same rigorous way — the pattern match
  (Garmin gating composite/coaching metrics behind higher device tiers) is strong
  enough to treat as the working explanation. `activities.training_load` will need
  to come from BJJ's `computed_load` and Strava's sparse historical column, not
  Garmin, on this hardware.
- **`training_readiness` will stay permanently NULL for Francisco's account, confirmed
  2026-08-28.** First real run returned no snapshots for any date; investigated by
  calling the raw (untyped) `get_training_readiness` endpoint directly and
  `client.get_devices()` — the raw endpoint genuinely returns `[]` (no mapping bug on
  our side), and the account's Forerunner 165 simply doesn't compute Training
  Readiness at all (a deliberate Garmin device-tier limitation, confirmed against
  Garmin's own FR165 manual and community forum, plus an independent device-support
  tracker). This is not a history-length issue the way this project's own HRV baseline
  seed phase is — no amount of waiting will populate it on this hardware. The kickoff
  doc's framing of computing our own readiness "alongside Garmin's Training Readiness
  so disagreement is visible" (`metrics/readiness.py`'s module docstring) doesn't apply
  here: there is no Garmin composite to compare against on this account, only our own.
