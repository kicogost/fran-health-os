"""Typed row representations for the canonical schema (core/schema.sql).

Thin dataclasses, not an ORM. `to_row()` produces a dict ready for `db.upsert()`;
`from_row()` reconstructs one from a `sqlite3.Row`. Bookkeeping columns the database
manages itself (`created_at`, `updated_at`, `computed_at`) are deliberately not
modeled here — they're audit trail, not domain data.

`to_row()` omits `None`-valued optional fields by default. This matters: ingestion
runs are frequently partial (a Garmin sync populates most of `daily_metrics`, a
separate Apple-Health/Renpho sync fills in just `weight_kg` for the same date later).
If `to_row()` always emitted every field, the second upsert would overwrite the
first sync's real values with NULL. Pass `include_none=True` to force a field to
NULL explicitly (e.g. correcting a bad ingest) — that's the deliberate exception, not
the default.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from dataclasses import dataclass
from typing import Any


def _row_dict(obj: Any, *, include_none: bool) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        value = getattr(obj, f.name)
        if value is None and not include_none:
            continue
        row[f.name] = value
    return row


def _load_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


@dataclass(slots=True)
class DailyMetric:
    """One row of `daily_metrics` — grain: one calendar date (Europe/Madrid)."""

    date: str
    weight_kg: float | None = None
    resting_hr: float | None = None
    hrv_overnight_ms: float | None = None
    hrv_status: str | None = None
    sleep_total_min: int | None = None
    sleep_deep_min: int | None = None
    sleep_rem_min: int | None = None
    sleep_light_min: int | None = None
    sleep_awake_min: int | None = None
    sleep_score: int | None = None
    body_battery_max: int | None = None
    body_battery_min: int | None = None
    stress_avg: int | None = None
    steps: int | None = None
    active_kcal: int | None = None
    total_kcal: int | None = None
    vo2max: float | None = None
    training_readiness: int | None = None
    respiration_avg: float | None = None
    spo2_avg: float | None = None
    skin_temp_delta: float | None = None
    sources: dict[str, str] | None = None

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        return _row_dict(self, include_none=include_none)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> DailyMetric:
        keys = row.keys()
        return cls(
            date=row["date"],
            weight_kg=row["weight_kg"] if "weight_kg" in keys else None,
            resting_hr=row["resting_hr"] if "resting_hr" in keys else None,
            hrv_overnight_ms=row["hrv_overnight_ms"] if "hrv_overnight_ms" in keys else None,
            hrv_status=row["hrv_status"] if "hrv_status" in keys else None,
            sleep_total_min=row["sleep_total_min"] if "sleep_total_min" in keys else None,
            sleep_deep_min=row["sleep_deep_min"] if "sleep_deep_min" in keys else None,
            sleep_rem_min=row["sleep_rem_min"] if "sleep_rem_min" in keys else None,
            sleep_light_min=row["sleep_light_min"] if "sleep_light_min" in keys else None,
            sleep_awake_min=row["sleep_awake_min"] if "sleep_awake_min" in keys else None,
            sleep_score=row["sleep_score"] if "sleep_score" in keys else None,
            body_battery_max=row["body_battery_max"] if "body_battery_max" in keys else None,
            body_battery_min=row["body_battery_min"] if "body_battery_min" in keys else None,
            stress_avg=row["stress_avg"] if "stress_avg" in keys else None,
            steps=row["steps"] if "steps" in keys else None,
            active_kcal=row["active_kcal"] if "active_kcal" in keys else None,
            total_kcal=row["total_kcal"] if "total_kcal" in keys else None,
            vo2max=row["vo2max"] if "vo2max" in keys else None,
            training_readiness=row["training_readiness"] if "training_readiness" in keys else None,
            respiration_avg=row["respiration_avg"] if "respiration_avg" in keys else None,
            spo2_avg=row["spo2_avg"] if "spo2_avg" in keys else None,
            skin_temp_delta=row["skin_temp_delta"] if "skin_temp_delta" in keys else None,
            sources=_load_json(row["sources"]) if "sources" in keys else None,
        )


@dataclass(slots=True)
class Activity:
    """One row of `activities` — one training session, from any source."""

    activity_id: str
    source: str
    source_id: str
    start_utc: str
    local_date: str
    sport: str | None = None
    sub_sport: str | None = None
    duration_s: int | None = None
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    hr_zone_1_s: int | None = None
    hr_zone_2_s: int | None = None
    hr_zone_3_s: int | None = None
    hr_zone_4_s: int | None = None
    hr_zone_5_s: int | None = None
    training_load: float | None = None
    aerobic_te: float | None = None
    anaerobic_te: float | None = None
    avg_power: float | None = None
    elevation_gain_m: float | None = None
    perceived_rpe: int | None = None
    merged_from: list[dict[str, str]] | None = None

    @staticmethod
    def make_id(source: str, source_id: str) -> str:
        return f"{source}:{source_id}"

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        return _row_dict(self, include_none=include_none)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Activity:
        keys = row.keys()
        return cls(
            activity_id=row["activity_id"],
            source=row["source"],
            source_id=row["source_id"],
            start_utc=row["start_utc"],
            local_date=row["local_date"],
            sport=row["sport"] if "sport" in keys else None,
            sub_sport=row["sub_sport"] if "sub_sport" in keys else None,
            duration_s=row["duration_s"] if "duration_s" in keys else None,
            distance_m=row["distance_m"] if "distance_m" in keys else None,
            avg_hr=row["avg_hr"] if "avg_hr" in keys else None,
            max_hr=row["max_hr"] if "max_hr" in keys else None,
            hr_zone_1_s=row["hr_zone_1_s"] if "hr_zone_1_s" in keys else None,
            hr_zone_2_s=row["hr_zone_2_s"] if "hr_zone_2_s" in keys else None,
            hr_zone_3_s=row["hr_zone_3_s"] if "hr_zone_3_s" in keys else None,
            hr_zone_4_s=row["hr_zone_4_s"] if "hr_zone_4_s" in keys else None,
            hr_zone_5_s=row["hr_zone_5_s"] if "hr_zone_5_s" in keys else None,
            training_load=row["training_load"] if "training_load" in keys else None,
            aerobic_te=row["aerobic_te"] if "aerobic_te" in keys else None,
            anaerobic_te=row["anaerobic_te"] if "anaerobic_te" in keys else None,
            avg_power=row["avg_power"] if "avg_power" in keys else None,
            elevation_gain_m=row["elevation_gain_m"] if "elevation_gain_m" in keys else None,
            perceived_rpe=row["perceived_rpe"] if "perceived_rpe" in keys else None,
            merged_from=_load_json(row["merged_from"]) if "merged_from" in keys else None,
        )


SESSION_FEELINGS = ("dizzy", "gassed", "tired", "okay")  # worst to best


@dataclass(slots=True)
class BjjSession:
    """One row of `bjj_sessions` — the manual log (kickoff doc section 2.4).

    `rounds_gassed` and `session_feeling` (migration 0002) are the athlete's own
    three BJJ-specific tracking questions, alongside `rounds_rolled`. `dizzy` in
    `session_feeling` is a genuine safety signal — worse than ordinary hard-session
    fatigue — not just the bottom of a tiredness scale.
    """

    date: str
    session_type: str  # "class" | "open_mat" | "gi_drilling"
    duration_min: int
    session_rpe: int  # 1-10
    id: int | None = None
    rounds_rolled: int | None = None
    rounds_gassed: int | None = None
    session_feeling: str | None = None  # one of SESSION_FEELINGS
    niggles: str | None = None
    notes: str | None = None
    computed_load: float | None = None
    linked_activity_id: str | None = None

    def __post_init__(self) -> None:
        if self.session_type not in ("class", "open_mat", "gi_drilling"):
            raise ValueError(f"invalid session_type: {self.session_type!r}")
        if not 1 <= self.session_rpe <= 10:
            raise ValueError(f"session_rpe must be 1-10, got {self.session_rpe!r}")
        if self.session_feeling is not None and self.session_feeling not in SESSION_FEELINGS:
            raise ValueError(f"invalid session_feeling: {self.session_feeling!r}")
        if (
            self.rounds_gassed is not None
            and self.rounds_rolled is not None
            and self.rounds_gassed > self.rounds_rolled
        ):
            raise ValueError(
                f"rounds_gassed ({self.rounds_gassed}) can't exceed "
                f"rounds_rolled ({self.rounds_rolled})"
            )
        if self.computed_load is None:
            self.computed_load = float(self.duration_min * self.session_rpe)

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        return _row_dict(self, include_none=include_none)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> BjjSession:
        keys = row.keys()
        return cls(
            id=row["id"] if "id" in keys else None,
            date=row["date"],
            session_type=row["session_type"],
            duration_min=row["duration_min"],
            rounds_rolled=row["rounds_rolled"] if "rounds_rolled" in keys else None,
            rounds_gassed=row["rounds_gassed"] if "rounds_gassed" in keys else None,
            session_feeling=row["session_feeling"] if "session_feeling" in keys else None,
            session_rpe=row["session_rpe"],
            niggles=row["niggles"] if "niggles" in keys else None,
            notes=row["notes"] if "notes" in keys else None,
            computed_load=row["computed_load"] if "computed_load" in keys else None,
            linked_activity_id=row["linked_activity_id"] if "linked_activity_id" in keys else None,
        )


_HOOPER_FIELDS = ("sleep_quality", "stress", "fatigue", "muscle_soreness")


@dataclass(slots=True)
class SubjectiveLogEntry:
    """One row of `subjective_log` — grain: one calendar date.

    `sleep_quality`/`stress`/`fatigue`/`muscle_soreness` (migration 0002) are a
    Hooper-Mackinnon-inspired daily wellness questionnaire: each 1-10, and
    deliberately all the SAME polarity (1 = best, 10 = worst) so they sum
    cleanly into `hooper_index` (4 = excellent wellness, 40 = terrible) without
    needing to remember which fields invert. `hooper_index` is computed here
    automatically, same pattern as `BjjSession.computed_load` — never entered
    by hand, and only set once all four sub-scores are present (a partial sum
    would misrepresent the day, not just be imprecise).
    """

    date: str
    felt_note: str | None = None
    protein_hit: bool | None = None
    gassed: bool | None = None
    niggles: str | None = None
    day_note: str | None = None
    social_meal: bool | None = None
    sleep_quality: int | None = None
    stress: int | None = None
    fatigue: int | None = None
    muscle_soreness: int | None = None
    hooper_index: int | None = None

    def __post_init__(self) -> None:
        for field_name in _HOOPER_FIELDS:
            value = getattr(self, field_name)
            if value is not None and not 1 <= value <= 10:
                raise ValueError(f"{field_name} must be 1-10, got {value!r}")
        sub_scores = [getattr(self, f) for f in _HOOPER_FIELDS]
        if self.hooper_index is None and all(s is not None for s in sub_scores):
            self.hooper_index = sum(sub_scores)

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        row = _row_dict(self, include_none=include_none)
        for col in ("protein_hit", "gassed", "social_meal"):
            if col in row and row[col] is not None:
                row[col] = int(row[col])
        return row

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SubjectiveLogEntry:
        keys = row.keys()

        def _bool(col: str) -> bool | None:
            return bool(row[col]) if col in keys and row[col] is not None else None

        def _int(col: str) -> int | None:
            return row[col] if col in keys else None

        return cls(
            date=row["date"],
            felt_note=row["felt_note"] if "felt_note" in keys else None,
            protein_hit=_bool("protein_hit"),
            gassed=_bool("gassed"),
            niggles=row["niggles"] if "niggles" in keys else None,
            day_note=row["day_note"] if "day_note" in keys else None,
            social_meal=_bool("social_meal"),
            sleep_quality=_int("sleep_quality"),
            stress=_int("stress"),
            fatigue=_int("fatigue"),
            muscle_soreness=_int("muscle_soreness"),
            hooper_index=_int("hooper_index"),
        )


@dataclass(slots=True)
class BodyMeasurement:
    """One row of `body_measurements` — grain: (date, measurement_type)."""

    date: str
    value_cm: float
    measurement_type: str = "waist"
    notes: str | None = None

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        return _row_dict(self, include_none=include_none)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> BodyMeasurement:
        keys = row.keys()
        return cls(
            date=row["date"],
            value_cm=row["value_cm"],
            measurement_type=row["measurement_type"] if "measurement_type" in keys else "waist",
            notes=row["notes"] if "notes" in keys else None,
        )


@dataclass(slots=True)
class DerivedMetric:
    """One row of `derived_daily` — grain: (date, metric_name).

    See kickoff doc section 6 for the full list of metrics this holds (HRV
    baseline, CTL/ATL/TSB, monotony/strain, readiness score + components, ... —
    ADR 0003 replaces the kickoff doc's ACWR with CTL/ATL/TSB). `inputs` is the
    traceability payload (design principle 9) — the actual input values and
    intermediate arithmetic that produced `value`, so any dashboard number can be
    explained down to its inputs.
    """

    date: str
    metric_name: str
    value: float | None = None
    unit: str | None = None
    window_days: int | None = None
    n_days: int | None = None
    confidence: str | None = None
    inputs: dict[str, Any] | None = None

    def to_row(self, *, include_none: bool = False) -> dict[str, Any]:
        row = _row_dict(self, include_none=include_none)
        if "inputs" in row:
            row["inputs_json"] = row.pop("inputs")
        return row

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> DerivedMetric:
        keys = row.keys()
        return cls(
            date=row["date"],
            metric_name=row["metric_name"],
            value=row["value"] if "value" in keys else None,
            unit=row["unit"] if "unit" in keys else None,
            window_days=row["window_days"] if "window_days" in keys else None,
            n_days=row["n_days"] if "n_days" in keys else None,
            confidence=row["confidence"] if "confidence" in keys else None,
            inputs=_load_json(row["inputs_json"]) if "inputs_json" in keys else None,
        )


@dataclass(slots=True)
class IngestRun:
    """One row of `ingest_runs` — read-only view; written via db.start/finish_ingest_run."""

    id: int
    source: str
    started_at: str
    status: str
    finished_at: str | None = None
    rows_in: int | None = None
    rows_upserted: int | None = None
    rows_skipped: int | None = None
    errors: list[str] | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> IngestRun:
        keys = row.keys()
        return cls(
            id=row["id"],
            source=row["source"],
            started_at=row["started_at"],
            status=row["status"],
            finished_at=row["finished_at"] if "finished_at" in keys else None,
            rows_in=row["rows_in"] if "rows_in" in keys else None,
            rows_upserted=row["rows_upserted"] if "rows_upserted" in keys else None,
            rows_skipped=row["rows_skipped"] if "rows_skipped" in keys else None,
            errors=_load_json(row["errors"]) if "errors" in keys else None,
        )
