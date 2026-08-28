"""Garmin bulk-export parser (kickoff doc section 2.1, Phase 2).

Parses the GDPR-style "Export Your Data" archive from Garmin's Account
Management Center. This is NOT a small, single-purpose export like Strava's or
Apple Health's — it's a dump of literally every Garmin product line the account
has ever touched (aviation, golf, InReach, Navionics, Tacx...), of which
health/fitness is one folder among many. Only two things are extracted here:

1. **Activities** (`DI_CONNECT/DI-Connect-Fitness/*summarizedActivities.json`)
   -> `activities`.
2. **Daily wellness** — three separate JSON sources merged per calendar date:
   - `DI_CONNECT/DI-Connect-Aggregator/UDSFile_*.json` ("User Daily Summary"):
     steps, calories, resting HR, body battery, all-day stress, respiration.
   - `DI_CONNECT/DI-Connect-Wellness/*_sleepData.json`: sleep stages + score.
     `calendarDate` here is ALREADY the wake-date (verified against real data)
     — Garmin does this attribution for us, matching design principle 7.
   - `DI_CONNECT/DI-Connect-Wellness/*_healthStatusData.json` ("LHA" —
     Garmin's internal name for baseline-deviation tracking): HRV, SpO2, skin
     temperature, each with Garmin's own baseline/status classification.

Files are located via `rglob()` from whatever base directory is passed, not a
fixed relative path — the real export nests everything inside a UUID-named
folder (`bulk_export/<uuid>_1/DI_CONNECT/...`) that's different every time a
fresh export is requested.

Real-export gotchas, verified against Francisco's actual export (2026-08-28),
not assumed:
- `distance` and `elevationGain`/`elevationLoss` on activities are in
  CENTIMETERS, not meters (divide by 100). Verified two ways: dividing by 100
  turned raw distance values into exactly 5.02km/5.01km/3.01km for three real
  runs (obviously-round training distances); dividing a real ride's
  `elevationGain` by 100 gave 630m, matching exactly what Strava recorded for
  what's very likely the same real ride (same date, same ~51km distance) —
  dividing by 1000 instead (a first, wrong guess) gave an implausible 63m for
  hilly Mallorca terrain.
- `duration` and related fields are in MILLISECONDS (divide by 1000).
- There is no single Garmin "training load" scalar in this export — Garmin
  represents training stress via `aerobicTrainingEffect`/
  `anaerobicTrainingEffect` (0-5 scale each), which map directly to
  `activities.aerobic_te`/`anaerobic_te`. `activities.training_load` stays
  NULL for Garmin-sourced rows as a result — never invented.
- Garmin's own `training_readiness` composite is NOT present anywhere in this
  bulk export (checked). It's only available live via the unofficial API
  (Phase 6), not this historical dump — stays NULL until then.
- HR zones come as 7 buckets (`hrTimeInZone_0`..`_6`) against our 5-zone
  schema. Folded conservatively: zone 0 (below zone 1) into zone 1, zone 6
  (above zone 5) into zone 5 — preserves total time-in-zone coverage rather
  than silently dropping the tails.
- VO2max appears both as a sparse dedicated file and opportunistically on
  individual running activities (`vO2MaxValue`) — not ingested here (only 4
  records total in the real export, event-triggered rather than daily; low
  value for the effort of a second parsing path). Known gap, not a silent one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from health_os.core.models import Activity, DailyMetric
from health_os.core.timezones import to_local_date, to_utc_iso
from health_os.ingest.common import normalize_sport_name

ACTIVITIES_GLOB = "*summarizedActivities.json"
UDS_GLOB = "UDSFile_*.json"
SLEEP_GLOB = "*_sleepData.json"
HEALTH_STATUS_GLOB = "*_healthStatusData.json"

_CM_TO_M = 0.01
_MS_TO_S = 0.001


def _find_files(base_dir: Path, pattern: str) -> list[Path]:
    return sorted(Path(base_dir).rglob(pattern))


def _ms_epoch_to_utc_iso(ms: float) -> str:
    return to_utc_iso(datetime.fromtimestamp(ms / 1000, tz=UTC))


def _fold_hr_zones(activity: dict[str, Any]) -> dict[str, int | None]:
    """7 Garmin buckets (0-6) -> our 5-zone schema — see module docstring."""
    if not any(f"hrTimeInZone_{i}" in activity for i in range(7)):
        return dict.fromkeys(f"hr_zone_{i}_s" for i in range(1, 6))

    def zone_s(idx: int) -> float:
        raw = activity.get(f"hrTimeInZone_{idx}")
        return raw * _MS_TO_S if raw is not None else 0.0

    return {
        "hr_zone_1_s": round(zone_s(0) + zone_s(1)),
        "hr_zone_2_s": round(zone_s(2)),
        "hr_zone_3_s": round(zone_s(3)),
        "hr_zone_4_s": round(zone_s(4)),
        "hr_zone_5_s": round(zone_s(5) + zone_s(6)),
    }


def _activity_to_model(a: dict[str, Any]) -> Activity | None:
    activity_id_raw = a.get("activityId")
    start_gmt = a.get("startTimeGmt")
    if activity_id_raw is None or start_gmt is None:
        return None

    source_id = str(int(activity_id_raw))
    start_utc = _ms_epoch_to_utc_iso(start_gmt)
    duration_ms = a.get("duration")
    distance_cm = a.get("distance")
    elevation_gain_cm = a.get("elevationGain")
    workout_rpe = a.get("workoutRpe")

    return Activity(
        activity_id=Activity.make_id("garmin", source_id),
        source="garmin",
        source_id=source_id,
        start_utc=start_utc,
        local_date=to_local_date(start_utc),
        sport=normalize_sport_name(a["activityType"]) if a.get("activityType") else None,
        duration_s=round(duration_ms * _MS_TO_S) if duration_ms is not None else None,
        distance_m=distance_cm * _CM_TO_M if distance_cm is not None else None,
        avg_hr=round(a["avgHr"]) if a.get("avgHr") is not None else None,
        max_hr=round(a["maxHr"]) if a.get("maxHr") is not None else None,
        aerobic_te=a.get("aerobicTrainingEffect"),
        anaerobic_te=a.get("anaerobicTrainingEffect"),
        avg_power=a.get("avgPower"),
        elevation_gain_m=elevation_gain_cm * _CM_TO_M if elevation_gain_cm is not None else None,
        perceived_rpe=round(workout_rpe) if workout_rpe else None,
        **_fold_hr_zones(a),
    )


def parse_activities(export_dir: Path) -> Iterator[Activity]:
    """Yield one `Activity` per record across every `*summarizedActivities.json`
    found under `export_dir` (there can be more than one part for a very long
    history — the real export names the first one with a `_1_` infix).
    """
    for path in _find_files(export_dir, ACTIVITIES_GLOB):
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        for page in payload:
            for raw in page.get("summarizedActivitiesExport", []):
                activity = _activity_to_model(raw)
                if activity is not None:
                    yield activity


def _extract_uds_fields(day: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "steps": day.get("totalSteps"),
        "resting_hr": day.get("restingHeartRate") or day.get("currentDayRestingHeartRate"),
    }
    if day.get("activeKilocalories") is not None:
        fields["active_kcal"] = round(day["activeKilocalories"])
    if day.get("totalKilocalories") is not None:
        fields["total_kcal"] = round(day["totalKilocalories"])

    for stat in (day.get("bodyBattery") or {}).get("bodyBatteryStatList", []):
        if stat.get("bodyBatteryStatType") == "HIGHEST":
            fields["body_battery_max"] = stat.get("statsValue")
        elif stat.get("bodyBatteryStatType") == "LOWEST":
            fields["body_battery_min"] = stat.get("statsValue")

    for agg in (day.get("allDayStress") or {}).get("aggregatorList", []):
        if agg.get("type") == "TOTAL":
            fields["stress_avg"] = agg.get("averageStressLevel")

    respiration_avg = (day.get("respiration") or {}).get("avgWakingRespirationValue")
    if respiration_avg is not None:
        fields["respiration_avg"] = respiration_avg

    return {k: v for k, v in fields.items() if v is not None}


def _extract_sleep_fields(day: dict[str, Any]) -> dict[str, Any]:
    deep, light, rem, awake = (
        day.get("deepSleepSeconds"),
        day.get("lightSleepSeconds"),
        day.get("remSleepSeconds"),
        day.get("awakeSleepSeconds"),
    )

    fields: dict[str, Any] = {}
    if deep is not None:
        fields["sleep_deep_min"] = round(deep / 60)
    if light is not None:
        fields["sleep_light_min"] = round(light / 60)
    if rem is not None:
        fields["sleep_rem_min"] = round(rem / 60)
    if awake is not None:
        fields["sleep_awake_min"] = round(awake / 60)
    if deep is not None and light is not None and rem is not None:
        # Actual sleep time, excluding awake periods within the sleep window.
        fields["sleep_total_min"] = round((deep + light + rem) / 60)

    overall_score = (day.get("sleepScores") or {}).get("overallScore")
    if overall_score is not None:
        fields["sleep_score"] = overall_score

    return fields


def _extract_health_status_fields(day: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for metric in day.get("metrics", []):
        value = metric.get("value")
        if value is None:
            continue
        if metric.get("type") == "HRV":
            fields["hrv_overnight_ms"] = value
            fields["hrv_status"] = metric.get("status")
        elif metric.get("type") == "SPO2":
            fields["spo2_avg"] = value
        elif metric.get("type") == "SKIN_TEMP_C":
            fields["skin_temp_delta"] = value
    return fields


def parse_daily_metrics(export_dir: Path) -> Iterator[DailyMetric]:
    """Merge UDS + sleep + health-status JSON into one `DailyMetric` per
    calendar date. Every populated field is tagged `"garmin"` in `sources`
    (design principle 9) — later merge passes against other sources can see
    exactly where each value came from.
    """
    by_date: dict[str, dict[str, Any]] = {}

    for path in _find_files(export_dir, UDS_GLOB):
        with path.open(encoding="utf-8") as f:
            for day in json.load(f):
                date = day.get("calendarDate")
                if date:
                    by_date.setdefault(date, {}).update(_extract_uds_fields(day))

    for path in _find_files(export_dir, SLEEP_GLOB):
        with path.open(encoding="utf-8") as f:
            for day in json.load(f):
                date = day.get("calendarDate")  # already the wake date
                if date:
                    by_date.setdefault(date, {}).update(_extract_sleep_fields(day))

    for path in _find_files(export_dir, HEALTH_STATUS_GLOB):
        with path.open(encoding="utf-8") as f:
            for day in json.load(f):
                date = day.get("calendarDate")
                if date:
                    by_date.setdefault(date, {}).update(_extract_health_status_fields(day))

    for date in sorted(by_date):
        fields = by_date[date]
        yield DailyMetric(date=date, sources=dict.fromkeys(fields, "garmin"), **fields)
