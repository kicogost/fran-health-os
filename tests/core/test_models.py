from __future__ import annotations

import sqlite3

import pytest

from health_os.core import db as db_module
from health_os.core.models import (
    Activity,
    BjjSession,
    BodyMeasurement,
    DailyMetric,
    DerivedMetric,
    IngestRun,
    SubjectiveLogEntry,
)


class TestDailyMetric:
    def test_to_row_omits_none_by_default(self) -> None:
        m = DailyMetric(date="2026-08-27", weight_kg=78.45)
        row = m.to_row()
        assert row == {"date": "2026-08-27", "weight_kg": 78.45}

    def test_to_row_include_none(self) -> None:
        m = DailyMetric(date="2026-08-27", weight_kg=78.45)
        row = m.to_row(include_none=True)
        assert row["resting_hr"] is None
        assert row["weight_kg"] == 78.45

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        m = DailyMetric(
            date="2026-08-27",
            weight_kg=78.45,
            resting_hr=52.0,
            sources={"weight_kg": "apple_health:renpho", "resting_hr": "garmin"},
        )
        db_module.upsert(conn, "daily_metrics", m.to_row(), ["date"])
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)).fetchone()
        reloaded = DailyMetric.from_row(row)
        assert reloaded.date == "2026-08-27"
        assert reloaded.weight_kg == 78.45
        assert reloaded.resting_hr == 52.0
        assert reloaded.sources == {"weight_kg": "apple_health:renpho", "resting_hr": "garmin"}
        assert reloaded.hrv_overnight_ms is None


class TestActivity:
    def test_make_id(self) -> None:
        assert Activity.make_id("garmin", "123") == "garmin:123"

    def test_round_trip_with_merged_from(self, conn: sqlite3.Connection) -> None:
        a = Activity(
            activity_id=Activity.make_id("garmin", "123"),
            source="garmin",
            source_id="123",
            start_utc="2026-08-27T17:00:00Z",
            local_date="2026-08-27",
            sport="cardio",
            duration_s=5400,
            merged_from=[{"source": "strava", "source_id": "999"}],
        )
        db_module.upsert(conn, "activities", a.to_row(), ["source", "source_id"])
        row = conn.execute(
            "SELECT * FROM activities WHERE activity_id = ?", (a.activity_id,)
        ).fetchone()
        reloaded = Activity.from_row(row)
        assert reloaded.sport == "cardio"
        assert reloaded.merged_from == [{"source": "strava", "source_id": "999"}]


class TestBjjSession:
    def test_computed_load_uses_fosters_method(self) -> None:
        s = BjjSession(date="2026-08-27", session_type="class", duration_min=90, session_rpe=7)
        assert s.computed_load == 630.0

    def test_explicit_computed_load_not_overwritten(self) -> None:
        s = BjjSession(
            date="2026-08-27",
            session_type="class",
            duration_min=90,
            session_rpe=7,
            computed_load=500.0,
        )
        assert s.computed_load == 500.0

    def test_rejects_invalid_session_type(self) -> None:
        with pytest.raises(ValueError):
            BjjSession(date="2026-08-27", session_type="sparring", duration_min=90, session_rpe=7)

    def test_rejects_out_of_range_rpe(self) -> None:
        with pytest.raises(ValueError):
            BjjSession(date="2026-08-27", session_type="class", duration_min=90, session_rpe=11)

    def test_round_trip_rounds_gassed_and_feeling(self, conn: sqlite3.Connection) -> None:
        s = BjjSession(
            date="2026-08-27",
            session_type="open_mat",
            duration_min=120,
            session_rpe=9,
            rounds_rolled=8,
            rounds_gassed=3,
            session_feeling="gassed",
            niggles="left knee tender",
        )
        db_module.upsert(conn, "bjj_sessions", s.to_row(), ["date", "session_type"])
        row = conn.execute(
            "SELECT * FROM bjj_sessions WHERE date = ? AND session_type = ?",
            ("2026-08-27", "open_mat"),
        ).fetchone()
        reloaded = BjjSession.from_row(row)
        assert reloaded.rounds_rolled == 8
        assert reloaded.rounds_gassed == 3
        assert reloaded.session_feeling == "gassed"
        assert reloaded.computed_load == 1080.0

    def test_rejects_invalid_session_feeling(self) -> None:
        with pytest.raises(ValueError):
            BjjSession(
                date="2026-08-27",
                session_type="class",
                duration_min=90,
                session_rpe=7,
                session_feeling="exhausted",
            )

    def test_rejects_rounds_gassed_exceeding_rounds_rolled(self) -> None:
        with pytest.raises(ValueError):
            BjjSession(
                date="2026-08-27",
                session_type="class",
                duration_min=90,
                session_rpe=7,
                rounds_rolled=3,
                rounds_gassed=5,
            )


class TestSubjectiveLogEntry:
    def test_round_trip_booleans(self, conn: sqlite3.Connection) -> None:
        e = SubjectiveLogEntry(date="2026-08-27", protein_hit=True, gassed=False, social_meal=True)
        db_module.upsert(conn, "subjective_log", e.to_row(), ["date"])
        row = conn.execute(
            "SELECT * FROM subjective_log WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        reloaded = SubjectiveLogEntry.from_row(row)
        assert reloaded.protein_hit is True
        assert reloaded.gassed is False
        assert reloaded.social_meal is True
        assert reloaded.niggles is None

    def test_hooper_index_computed_when_all_four_present(self) -> None:
        e = SubjectiveLogEntry(
            date="2026-08-27", sleep_quality=3, stress=2, fatigue=4, muscle_soreness=5
        )
        assert e.hooper_index == 14

    def test_hooper_index_not_computed_when_partial(self) -> None:
        e = SubjectiveLogEntry(date="2026-08-27", sleep_quality=3, stress=2)
        assert e.hooper_index is None

    def test_explicit_hooper_index_not_overwritten(self) -> None:
        e = SubjectiveLogEntry(
            date="2026-08-27",
            sleep_quality=3,
            stress=2,
            fatigue=4,
            muscle_soreness=5,
            hooper_index=99,
        )
        assert e.hooper_index == 99

    def test_rejects_out_of_range_wellness_score(self) -> None:
        with pytest.raises(ValueError):
            SubjectiveLogEntry(date="2026-08-27", sleep_quality=11)

    def test_round_trip_wellness_fields(self, conn: sqlite3.Connection) -> None:
        e = SubjectiveLogEntry(
            date="2026-08-27", sleep_quality=2, stress=3, fatigue=2, muscle_soreness=4
        )
        db_module.upsert(conn, "subjective_log", e.to_row(), ["date"])
        row = conn.execute(
            "SELECT * FROM subjective_log WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        reloaded = SubjectiveLogEntry.from_row(row)
        assert reloaded.sleep_quality == 2
        assert reloaded.hooper_index == 11


class TestBodyMeasurement:
    def test_default_measurement_type_is_waist(self) -> None:
        m = BodyMeasurement(date="2026-08-30", value_cm=85.5)
        assert m.measurement_type == "waist"

    def test_round_trip(self, conn: sqlite3.Connection) -> None:
        m = BodyMeasurement(date="2026-08-30", value_cm=85.5, notes="post-camp Block 1")
        db_module.upsert(conn, "body_measurements", m.to_row(), ["date", "measurement_type"])
        row = conn.execute(
            "SELECT * FROM body_measurements WHERE date = ? AND measurement_type = ?",
            ("2026-08-30", "waist"),
        ).fetchone()
        reloaded = BodyMeasurement.from_row(row)
        assert reloaded.value_cm == 85.5
        assert reloaded.notes == "post-camp Block 1"


class TestDerivedMetric:
    def test_inputs_round_trip_as_json(self, conn: sqlite3.Connection) -> None:
        m = DerivedMetric(
            date="2026-08-27",
            metric_name="acwr",
            value=1.12,
            unit="ratio",
            window_days=28,
            n_days=28,
            confidence="full",
            inputs={"acute_load": 450, "chronic_load": 402},
        )
        db_module.upsert(
            conn, "derived_daily", m.to_row(), ["date", "metric_name"], touch_column=None
        )
        row = conn.execute(
            "SELECT * FROM derived_daily WHERE date = ? AND metric_name = ?", ("2026-08-27", "acwr")
        ).fetchone()
        reloaded = DerivedMetric.from_row(row)
        assert reloaded.value == 1.12
        assert reloaded.inputs == {"acute_load": 450, "chronic_load": 402}


class TestIngestRun:
    def test_from_row(self, conn: sqlite3.Connection) -> None:
        run_id = db_module.start_ingest_run(conn, "garmin")
        db_module.finish_ingest_run(
            conn, run_id, status="success", rows_in=5, rows_upserted=5, rows_skipped=0
        )
        row = conn.execute("SELECT * FROM ingest_runs WHERE id = ?", (run_id,)).fetchone()
        reloaded = IngestRun.from_row(row)
        assert reloaded.source == "garmin"
        assert reloaded.status == "success"
        assert reloaded.rows_upserted == 5
