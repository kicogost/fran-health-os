"""Log page backend — read (existing-entry checks, for the overwrite
warning) and write (real upserts) for all four manual logs: BJJ session,
daily wellness, waist measurement, calisthenics session.

Every write goes through the SAME dataclasses (`core/models.py`) the CLI
scripts (`scripts/log_bjj.py` etc.) and the Streamlit dashboard already use
— validation lives in one place (`__post_init__`), never duplicated into
this API layer. A `ValueError` from a dataclass constructor is caught and
returned as a 422 with the exact message, mirroring the Streamlit page's
own `st.error(str(exc))` pattern.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel

from health_os.core import db
from health_os.core.models import (
    BjjSession,
    BodyMeasurement,
    CalisthenicsSession,
    SubjectiveLogEntry,
    merge_subjective_log_entry,
)


class BjjSessionRequest(BaseModel):
    date: str
    session_type: str
    duration_min: int
    session_rpe: int
    rounds_rolled: int | None = None
    rounds_gassed: int | None = None
    session_feeling: str | None = None
    niggles: str | None = None
    notes: str | None = None


class WellnessRequest(BaseModel):
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


class WaistRequest(BaseModel):
    date: str
    value_cm: float
    notes: str | None = None


class ExerciseEntry(BaseModel):
    exercise: str
    sets: int
    reps: int | None = None
    added_weight_kg: float | None = None
    notes: str | None = None


class CalisthenicsRequest(BaseModel):
    date: str
    session_type: str
    session_rpe: int | None = None
    exercises: list[ExerciseEntry] | None = None
    notes: str | None = None


# ---------------------------------------------------------------- BJJ ----


def get_existing_bjj(
    conn: sqlite3.Connection, date: str, session_type: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT duration_min, session_rpe, computed_load FROM bjj_sessions "
        "WHERE date = ? AND session_type = ?",
        (date, session_type),
    ).fetchone()
    return dict(row) if row is not None else None


def save_bjj(conn: sqlite3.Connection, req: BjjSessionRequest) -> BjjSession:
    session = BjjSession(**req.model_dump())
    db.upsert(conn, "bjj_sessions", session.to_row(), ["date", "session_type"])
    return session


# ---------------------------------------------------------- Wellness ----


def get_existing_wellness(conn: sqlite3.Connection, date: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT hooper_index FROM subjective_log WHERE date = ?", (date,)).fetchone()
    return dict(row) if row is not None else None


def save_wellness(conn: sqlite3.Connection, req: WellnessRequest) -> SubjectiveLogEntry:
    entry = SubjectiveLogEntry(**req.model_dump())
    # Merge with any existing row for this date FIRST -- hooper_index can
    # only be computed once all 4 sub-scores are known, which may have been
    # logged across separate calls (see merge_subjective_log_entry's
    # docstring for the real bug this avoids).
    entry = merge_subjective_log_entry(conn, entry)
    db.upsert(conn, "subjective_log", entry.to_row(), ["date"])
    return entry


# ------------------------------------------------------------- Waist ----


def get_existing_waist(conn: sqlite3.Connection, date: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value_cm FROM body_measurements WHERE date = ? AND measurement_type = 'waist'",
        (date,),
    ).fetchone()
    return dict(row) if row is not None else None


def save_waist(conn: sqlite3.Connection, req: WaistRequest) -> BodyMeasurement:
    measurement = BodyMeasurement(
        date=req.date, measurement_type="waist", value_cm=req.value_cm, notes=req.notes
    )
    db.upsert(conn, "body_measurements", measurement.to_row(), ["date", "measurement_type"])
    return measurement


# ------------------------------------------------------- Calisthenics ----


def get_existing_calisthenics(
    conn: sqlite3.Connection, date: str, session_type: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT session_rpe FROM calisthenics_sessions WHERE date = ? AND session_type = ?",
        (date, session_type),
    ).fetchone()
    return dict(row) if row is not None else None


def save_calisthenics(conn: sqlite3.Connection, req: CalisthenicsRequest) -> CalisthenicsSession:
    exercises = [e.model_dump() for e in req.exercises] if req.exercises else None
    session = CalisthenicsSession(
        date=req.date,
        session_type=req.session_type,
        session_rpe=req.session_rpe,
        exercises=exercises,
        notes=req.notes,
    )
    db.upsert(conn, "calisthenics_sessions", session.to_row(), ["date", "session_type"])
    return session


def prescribed_exercises(config: dict[str, Any], session_type: str) -> list[str]:
    return (
        config.get("comp_prep", {})
        .get("strength_sessions", {})
        .get(session_type, {})
        .get("exercises", [])
    )
