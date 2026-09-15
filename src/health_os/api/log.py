"""Log page backend — read (existing-entry checks, for the overwrite
warning) and write (real upserts) for all five daily manual logs: BJJ
session, daily wellness, waist measurement, calisthenics session, illness
log — plus (2026-09-14) the 5 general health-history tables (bloodwork,
medical events, medications/supplements, allergies, family medical history),
which back the separate "Health History" frontend page rather than the daily
"Log" page, since they're occasional historical records, not a daily habit.

Every write goes through the SAME dataclasses (`core/models.py`) the CLI
scripts (`scripts/log_bjj.py`, `scripts/log_health_history.py`, ...) already
use — validation lives in one place (`__post_init__`), never duplicated into
this API layer. A `ValueError` from a dataclass constructor is caught and
returned as a 422 with the exact message, mirroring the Streamlit page's
own `st.error(str(exc))` pattern.

Health-history note: bloodwork/medical_events/medications_supplements have
no natural key (design principle 2 — a fresh record every time, see
migration 0009's header comment), so their `save_*` functions call
`db.insert()`, never `db.upsert()`, and there's no "existing entry" check to
expose (there's nothing to warn about overwriting). Allergies and family
medical history DO have a natural key and get the same
get_existing/save/warn-before-overwrite shape as the five daily logs above.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import BaseModel

from health_os.core import db
from health_os.core.models import (
    Allergy,
    BjjSession,
    BloodworkResult,
    BodyMeasurement,
    CalisthenicsSession,
    FamilyMedicalHistory,
    IllnessLog,
    MedicalEvent,
    MedicationSupplement,
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
    duration_min: int | None = None


class IllnessRequest(BaseModel):
    date: str
    severity: int | None = None
    sore_throat: bool | None = None
    fever: bool | None = None
    temperature_c: float | None = None
    congestion: bool | None = None
    cough: bool | None = None
    body_aches: bool | None = None
    fatigue_weakness: bool | None = None
    headache: bool | None = None
    likely_cause: str | None = None
    notes: str | None = None


class BloodworkRequest(BaseModel):
    date: str
    test_name: str
    value: float
    unit: str | None = None
    reference_range_low: float | None = None
    reference_range_high: float | None = None
    notes: str | None = None


class MedicalEventRequest(BaseModel):
    date: str
    category: str
    title: str
    status: str
    resolved_date: str | None = None
    notes: str | None = None


class MedicationRequest(BaseModel):
    name: str
    type: str
    start_date: str
    dosage: str | None = None
    frequency: str | None = None
    end_date: str | None = None
    notes: str | None = None


class AllergyRequest(BaseModel):
    allergen: str
    reaction: str | None = None
    severity: str | None = None
    date_identified: str | None = None
    notes: str | None = None


class FamilyHistoryRequest(BaseModel):
    relation: str
    condition: str
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
        "SELECT session_rpe, duration_min, computed_load FROM calisthenics_sessions "
        "WHERE date = ? AND session_type = ?",
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
        duration_min=req.duration_min,
    )
    db.upsert(conn, "calisthenics_sessions", session.to_row(), ["date", "session_type"])
    return session


# ---------------------------------------------------------- Illness ----


def get_existing_illness(conn: sqlite3.Connection, date: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT severity FROM illness_log WHERE date = ?", (date,)).fetchone()
    return dict(row) if row is not None else None


def save_illness(conn: sqlite3.Connection, req: IllnessRequest) -> IllnessLog:
    entry = IllnessLog(**req.model_dump())
    db.upsert(conn, "illness_log", entry.to_row(), ["date"])
    return entry


def prescribed_exercises(config: dict[str, Any], session_type: str) -> list[str]:
    return (
        config.get("comp_prep", {})
        .get("strength_sessions", {})
        .get(session_type, {})
        .get("exercises", [])
    )


# ============================================================
# Health History (2026-09-14) — bloodwork, medical events, medications/
# supplements, allergies, family medical history. Backs the "Health
# History" frontend page, not the daily "Log" page — occasional historical
# records, not a daily habit. See migration 0009 / core/models.py for the
# full per-table design reasoning.
# ============================================================

# --------------------------------------------------------- Bloodwork ----


def list_bloodwork(
    conn: sqlite3.Connection, *, test_name: str | None = None, date: str | None = None
) -> list[BloodworkResult]:
    """Bloodwork's own GET supports three shapes: real history for one test
    across every draw date (trend view — `test_name`), everything from one
    draw date (a full panel — `date`), or, with neither given, the whole
    table (most recent draw first) for the Health History page's table view.
    """
    if test_name is not None:
        rows = conn.execute(
            "SELECT * FROM bloodwork_results WHERE test_name = ? ORDER BY date ASC, id ASC",
            (test_name,),
        ).fetchall()
    elif date is not None:
        rows = conn.execute(
            "SELECT * FROM bloodwork_results WHERE date = ? ORDER BY test_name ASC",
            (date,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM bloodwork_results ORDER BY date DESC, test_name ASC"
        ).fetchall()
    return [BloodworkResult.from_row(r) for r in rows]


def save_bloodwork(conn: sqlite3.Connection, req: BloodworkRequest) -> BloodworkResult:
    result = BloodworkResult(**req.model_dump())
    result.id = db.insert(conn, "bloodwork_results", result.to_row())
    return result


# ----------------------------------------------------- Medical events ----


def list_medical_events(conn: sqlite3.Connection) -> list[MedicalEvent]:
    rows = conn.execute("SELECT * FROM medical_events ORDER BY date DESC, id DESC").fetchall()
    return [MedicalEvent.from_row(r) for r in rows]


def save_medical_event(conn: sqlite3.Connection, req: MedicalEventRequest) -> MedicalEvent:
    event = MedicalEvent(**req.model_dump())
    event.id = db.insert(conn, "medical_events", event.to_row())
    return event


# --------------------------------------------- Medications / supplements ----


def list_medications(conn: sqlite3.Connection) -> list[MedicationSupplement]:
    rows = conn.execute(
        "SELECT * FROM medications_supplements ORDER BY start_date DESC, id DESC"
    ).fetchall()
    return [MedicationSupplement.from_row(r) for r in rows]


def save_medication(conn: sqlite3.Connection, req: MedicationRequest) -> MedicationSupplement:
    med = MedicationSupplement(**req.model_dump())
    med.id = db.insert(conn, "medications_supplements", med.to_row())
    return med


# ---------------------------------------------------------- Allergies ----


def list_allergies(conn: sqlite3.Connection) -> list[Allergy]:
    rows = conn.execute("SELECT * FROM allergies ORDER BY allergen ASC").fetchall()
    return [Allergy.from_row(r) for r in rows]


def get_existing_allergy(conn: sqlite3.Connection, allergen: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT severity FROM allergies WHERE allergen = ?", (allergen,)).fetchone()
    return dict(row) if row is not None else None


def save_allergy(conn: sqlite3.Connection, req: AllergyRequest) -> Allergy:
    allergy = Allergy(**req.model_dump())
    db.upsert(conn, "allergies", allergy.to_row(), ["allergen"])
    return allergy


# ---------------------------------------------- Family medical history ----


def list_family_history(conn: sqlite3.Connection) -> list[FamilyMedicalHistory]:
    rows = conn.execute(
        "SELECT * FROM family_medical_history ORDER BY relation ASC, condition ASC"
    ).fetchall()
    return [FamilyMedicalHistory.from_row(r) for r in rows]


def get_existing_family_history(
    conn: sqlite3.Connection, relation: str, condition: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT notes FROM family_medical_history WHERE relation = ? AND condition = ?",
        (relation, condition),
    ).fetchone()
    return dict(row) if row is not None else None


def save_family_history(
    conn: sqlite3.Connection, req: FamilyHistoryRequest
) -> FamilyMedicalHistory:
    entry = FamilyMedicalHistory(**req.model_dump())
    db.upsert(conn, "family_medical_history", entry.to_row(), ["relation", "condition"])
    return entry
