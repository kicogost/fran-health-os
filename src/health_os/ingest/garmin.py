"""Garmin live incremental sync (kickoff doc Phase 6), via the unofficial
`garminconnect` + `garth` client. NOT the historical bulk-export parser — see
`ingest/garmin_bulk.py` for that. Wrapped behind this one adapter module so a
Garmin login-flow or endpoint-shape breakage is a one-file fix, per CLAUDE.md's
"Data sources" section.

Auth: `garminconnect.Garmin(email, password, prompt_mfa=...)`, then
`.login(tokenstore)`. First run against an MFA-enabled account blocks on
`input()` for the 6-digit code; `garth` then persists session tokens under
`GARTH_TOKEN_DIR` so every subsequent run is headless (verified by reading the
installed library's `login()` source directly, not assumed — see conversation
notes / ADR 0004). Credentials come from `GARMIN_EMAIL`/`GARMIN_PASSWORD` env
vars only — never pass them as literals, never log them.

Daily wellness fetch uses `client.typed.*` (the library's own Pydantic-
validated response models, `garminconnect[typed]` extra) rather than
hand-parsing raw dicts, for four fields we've verified against the real,
installed library source (`garminconnect/typed.py`):
`get_stats`/`get_sleep_data`/`get_hrv_data`/`get_training_readiness`. Those
models' field names are self-documenting about units (`total_distance_meters`,
`sleeping_seconds`, ...) in a way the bulk export's raw JSON never was — see
ADR 0004 for the full reasoning, including why this is a deliberate deviation
from "hand-parse everything ourselves." A per-endpoint validation failure
(`GarminConnectResponseValidationError`, e.g. Garmin adds/renames a field
upstream) is caught and skipped rather than crashing the whole day's sync —
logged into `ingest_runs.errors` by the caller, never silently swallowed.

Live-activity units are NOT self-documented the same way (`typed.Activity`
fields are just `distance`/`duration`/`elevation_gain`, no unit suffix) — this
module assumes the standard Garmin Connect REST convention (seconds, meters),
which is a *different* convention from the bulk export's centimeters/
milliseconds (see `garmin_bulk.py`'s docstring for that history). This is a
documented assumption, not yet cross-validated against a real account the way
every other parser in this codebase was — `scripts/sync.py` prints each newly
synced activity's raw numbers so a wrong unit conversion is visible on the
first real run, the same spirit as the elevationGain cross-check in
`garmin_bulk.py`, just deferred to runtime instead of pre-verified.

Known gaps (consistent with `garmin_bulk.py`'s "known gap, not silent"
pattern):
- VO2max, SpO2, and skin temperature have raw (untyped) endpoints
  (`get_max_metrics`, `get_spo2_data`, ...) but no `typed` wrapper yet, so
  they are not fetched here.
- HR zones (`hr_zone_1_s`..`_5_s`) and `perceived_rpe` stay NULL for
  live-synced activities. `garmin_bulk.py` gets both from raw
  `hrTimeInZone_0..6`/`workoutRpe` keys on the bulk export's activity dict,
  but `typed.Activity` doesn't model either field, and unlike the fields
  above we have no verified evidence the live activity-list endpoint even
  includes them as extras, let alone with the bulk export's millisecond/scale
  convention — guessing that over would repeat exactly the kind of
  unverified-unit mistake `garmin_bulk.py`'s elevationGain history warns
  against. Left as a follow-up once a real live response can be inspected.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from garminconnect import Garmin
from garminconnect.typed import Activity as TypedActivity
from garminconnect.typed import GarminConnectResponseValidationError

from health_os.core.models import Activity, DailyMetric
from health_os.core.timezones import to_local_date, to_utc_iso
from health_os.ingest.common import normalize_sport_name

_SECONDS_TO_MINUTES = 1 / 60


def _prompt_mfa() -> str:
    return input("Garmin MFA code: ").strip()


def build_and_login_client(
    *,
    email: str | None = None,
    password: str | None = None,
    tokenstore: str | Path | None = None,
) -> Garmin:
    """Construct a `Garmin` client and log in, reading credentials/tokenstore
    path from env vars (`GARMIN_EMAIL`/`GARMIN_PASSWORD`/`GARTH_TOKEN_DIR`) by
    default. Blocks on an interactive MFA prompt only if cached tokens are
    absent/expired AND the account has MFA enabled.

    Raises `GarminConnectAuthenticationError` if credentials are missing and
    no valid cached tokens exist — a loud, specific failure rather than a
    generic exception, so `scripts/sync.py` can print a clear "add your
    credentials to .env" message instead of a stack trace.
    """
    email = email if email is not None else os.environ.get("GARMIN_EMAIL")
    password = password if password is not None else os.environ.get("GARMIN_PASSWORD")
    tokenstore = str(tokenstore or os.environ.get("GARTH_TOKEN_DIR", "data/.garth_tokens"))

    # Missing credentials aren't fatal here on their own — cached tokens under
    # `tokenstore` might still be valid, in which case login() never touches
    # username/password at all. Garmin.login() is the one that actually
    # decides, raising GarminConnectAuthenticationError if tokens are absent
    # AND credentials are missing.
    client = Garmin(email=email or None, password=password or None, prompt_mfa=_prompt_mfa)
    client.login(tokenstore)
    return client


def _parse_garmin_gmt_timestamp(value: str) -> str:
    """Garmin Connect's activity-list REST endpoint reports `startTimeGMT` as
    a space-separated string with no offset marker (e.g.
    "2026-08-27 17:03:21"), semantically already UTC — a well-established
    convention for this endpoint, distinct from the bulk export's millisecond
    epoch ints. Handles that shape; also tolerates a proper ISO8601 string
    (with 'T' and/or an explicit offset) in case a future library version
    normalizes it, rather than assuming only one shape forever.
    """
    candidate = value.strip()
    if "T" not in candidate:
        candidate = candidate.replace(" ", "T", 1)
    dt = datetime.fromisoformat(candidate)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return to_utc_iso(dt)


def _daterange(start: date, end: date) -> Iterator[date]:
    days = (end - start).days
    for i in range(days + 1):
        yield start + timedelta(days=i)


def _pick_morning_readiness(snapshots: list[Any]) -> Any | None:
    """Mirrors `get_morning_training_readiness`'s own fallback logic (verified
    against the installed library's source): prefer the snapshot recorded
    right after waking, else the most recent by timestamp, else the first.
    """
    if not snapshots:
        return None
    morning = next((s for s in snapshots if s.input_context == "AFTER_WAKEUP_RESET"), None)
    if morning is not None:
        return morning
    with_timestamp = [s for s in snapshots if s.timestamp]
    if with_timestamp:
        return max(with_timestamp, key=lambda s: s.timestamp)
    return snapshots[0]


def _fetch_one_day_metrics(
    client: Garmin, cdate: str, errors: list[str] | None
) -> DailyMetric | None:
    """One day's worth of `fetch_daily_metrics` — split out (rather than
    inlined in the loop below) so `fields`/`sources` are this call's own
    locals, not variables closed over across loop iterations.
    """
    fields: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def _record(name: str, value: Any) -> None:
        if value is not None:
            fields[name] = value
            sources[name] = "garmin"

    try:
        stats = client.typed.get_stats(cdate)
        _record("resting_hr", stats.resting_heart_rate)
        _record("steps", stats.total_steps)
        if stats.active_kilocalories is not None:
            _record("active_kcal", round(stats.active_kilocalories))
        if stats.total_kilocalories is not None:
            _record("total_kcal", round(stats.total_kilocalories))
        _record("stress_avg", stats.average_stress_level)
        _record("body_battery_max", stats.body_battery_highest_value)
        _record("body_battery_min", stats.body_battery_lowest_value)
    except GarminConnectResponseValidationError as exc:
        if errors is not None:
            errors.append(f"get_stats({cdate}) validation failed: {exc}")

    try:
        sleep = client.typed.get_sleep_data(cdate)
        dto = sleep.daily_sleep_dto
        if dto is not None:
            # sleep_time_seconds is the API's own canonical total (populated
            # whenever the stage breakdown is, per the same computation) —
            # preferred over re-deriving it from deep+light+rem the way
            # garmin_bulk.py has to (that export has no direct total field).
            if dto.sleep_time_seconds is not None:
                _record("sleep_total_min", round(dto.sleep_time_seconds * _SECONDS_TO_MINUTES))
            if dto.deep_sleep_seconds is not None:
                _record("sleep_deep_min", round(dto.deep_sleep_seconds * _SECONDS_TO_MINUTES))
            if dto.light_sleep_seconds is not None:
                _record("sleep_light_min", round(dto.light_sleep_seconds * _SECONDS_TO_MINUTES))
            if dto.rem_sleep_seconds is not None:
                _record("sleep_rem_min", round(dto.rem_sleep_seconds * _SECONDS_TO_MINUTES))
            if dto.awake_sleep_seconds is not None:
                _record("sleep_awake_min", round(dto.awake_sleep_seconds * _SECONDS_TO_MINUTES))
            if dto.sleep_scores and dto.sleep_scores.overall:
                _record("sleep_score", dto.sleep_scores.overall.value)
    except GarminConnectResponseValidationError as exc:
        if errors is not None:
            errors.append(f"get_sleep_data({cdate}) validation failed: {exc}")

    try:
        hrv = client.typed.get_hrv_data(cdate)  # None is a valid "no data" response
        if hrv is not None and hrv.hrv_summary is not None:
            _record("hrv_overnight_ms", hrv.hrv_summary.last_night_avg)
            _record("hrv_status", hrv.hrv_summary.status)
    except GarminConnectResponseValidationError as exc:
        if errors is not None:
            errors.append(f"get_hrv_data({cdate}) validation failed: {exc}")

    try:
        readiness = _pick_morning_readiness(client.typed.get_training_readiness(cdate))
        if readiness is not None:
            _record("training_readiness", readiness.score)
    except GarminConnectResponseValidationError as exc:
        if errors is not None:
            errors.append(f"get_training_readiness({cdate}) validation failed: {exc}")

    if not fields:
        return None
    return DailyMetric(date=cdate, sources=sources, **fields)


def fetch_daily_metrics(
    client: Garmin, start_date: date, end_date: date, *, errors: list[str] | None = None
) -> Iterator[DailyMetric]:
    """One `DailyMetric` per calendar date in `[start_date, end_date]`
    (inclusive) that has at least one populated field, from `get_stats`/
    `get_sleep_data`/`get_hrv_data`/`get_training_readiness` via the
    validated `client.typed` namespace.

    A validation failure on any one endpoint for any one date is appended to
    `errors` (if given) and that endpoint's fields are simply omitted for that
    date — never invented, never crashes the rest of the range.
    """
    for day in _daterange(start_date, end_date):
        metric = _fetch_one_day_metrics(client, day.isoformat(), errors)
        if metric is not None:
            yield metric


def _activity_to_model(a: Any) -> Activity | None:
    if a.activity_id is None or a.start_time_gmt is None:
        return None

    source_id = str(a.activity_id)
    start_utc = _parse_garmin_gmt_timestamp(a.start_time_gmt)
    sport = (
        normalize_sport_name(a.activity_type.type_key)
        if a.activity_type and a.activity_type.type_key
        else None
    )

    # Garmin's own `activityType` never changes for a custom-renamed "Other"
    # profile (a watch-side rename of "Otros" to e.g. "BJJ" still reports
    # sport="other" — confirmed 2026-08-28 against a real recording), but the
    # custom name itself DOES sync through as `activityName`. Storing it in
    # `sub_sport` for exactly this case (sport=="other" only — a properly
    # typed activity's name is just a title, not a sport classification, and
    # shouldn't be reinterpreted as one) is what makes these filterable later
    # despite Garmin's generic type. A plain `.lower()`, not
    # `normalize_sport_name()`: that function is built for CamelCase API
    # constants ("HKWorkoutActivityTypeMartialArts") and mangles a free-typed
    # acronym like "BJJ" into "b_j_j" — verified directly, not assumed.
    sub_sport = None
    if sport == "other" and a.activity_name:
        sub_sport = a.activity_name.strip().lower() or None

    # hr_zone_*_s / perceived_rpe intentionally omitted — see module
    # docstring's "Known gaps" section.
    return Activity(
        activity_id=Activity.make_id("garmin", source_id),
        source="garmin",
        source_id=source_id,
        start_utc=start_utc,
        local_date=to_local_date(start_utc),
        sport=sport,
        sub_sport=sub_sport,
        duration_s=round(a.duration) if a.duration is not None else None,
        distance_m=a.distance,
        avg_hr=round(a.average_hr) if a.average_hr is not None else None,
        max_hr=round(a.max_hr) if a.max_hr is not None else None,
        aerobic_te=a.aerobic_training_effect,
        anaerobic_te=a.anaerobic_training_effect,
        avg_power=a.avg_power,
        elevation_gain_m=a.elevation_gain,
        training_load=a.activity_training_load,
    )


def fetch_activities(
    client: Garmin, start_date: date, end_date: date, *, errors: list[str] | None = None
) -> Iterator[Activity]:
    """One `Activity` per record from `get_activities_by_date` in
    `[start_date, end_date]` (inclusive). See module docstring for the
    seconds/meters unit assumption. A single malformed activity is skipped
    (appended to `errors`) rather than failing the whole batch.
    """
    try:
        raw_activities = client.get_activities_by_date(start_date.isoformat(), end_date.isoformat())
    except Exception as exc:  # noqa: BLE001 - reported to caller, not swallowed
        if errors is not None:
            errors.append(f"get_activities_by_date({start_date}..{end_date}) failed: {exc}")
        return

    for raw in raw_activities:
        try:
            typed_activity = TypedActivity.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - one bad activity shouldn't drop the batch
            if errors is not None:
                errors.append(f"activity {raw.get('activityId', '?')} validation failed: {exc}")
            continue

        activity = _activity_to_model(typed_activity)
        if activity is not None:
            yield activity
