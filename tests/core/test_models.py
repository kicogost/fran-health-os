from __future__ import annotations

import sqlite3

import pytest

from health_os.core import db as db_module
from health_os.core.models import (
    Activity,
    ActivityLap,
    BjjSession,
    BodyMeasurement,
    CalisthenicsSession,
    DailyMetric,
    DerivedMetric,
    IngestRun,
    SubjectiveLogEntry,
    merge_subjective_log_entry,
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


class TestCalisthenicsSession:
    def test_rejects_invalid_session_type(self) -> None:
        with pytest.raises(ValueError):
            CalisthenicsSession(date="2026-08-24", session_type="strength_c")

    def test_rejects_out_of_range_rpe(self) -> None:
        with pytest.raises(ValueError):
            CalisthenicsSession(date="2026-08-24", session_type="strength_a", session_rpe=11)

    def test_session_rpe_and_exercises_are_optional(self) -> None:
        s = CalisthenicsSession(date="2026-08-24", session_type="strength_a")
        assert s.session_rpe is None
        assert s.exercises is None

    def test_round_trip_exercises_json(self, conn: sqlite3.Connection) -> None:
        exercises = [
            {"exercise": "pull-ups", "sets": 4, "reps": 5, "added_weight_kg": 5.0, "notes": None},
            {"exercise": "push-ups", "sets": 3, "reps": 8, "added_weight_kg": None, "notes": None},
        ]
        s = CalisthenicsSession(
            date="2026-08-24",
            session_type="strength_a",
            session_rpe=6,
            exercises=exercises,
            notes="felt strong",
        )
        db_module.upsert(conn, "calisthenics_sessions", s.to_row(), ["date", "session_type"])
        row = conn.execute(
            "SELECT * FROM calisthenics_sessions WHERE date = ? AND session_type = ?",
            ("2026-08-24", "strength_a"),
        ).fetchone()
        reloaded = CalisthenicsSession.from_row(row)
        assert reloaded.exercises == exercises
        assert reloaded.session_rpe == 6
        assert reloaded.notes == "felt strong"

    def test_to_row_omits_none_exercises_by_default(self) -> None:
        s = CalisthenicsSession(date="2026-08-24", session_type="strength_a")
        row = s.to_row()
        assert "exercises_json" not in row


def _insert_parent_activity(conn: sqlite3.Connection, activity_id: str = "garmin:123") -> None:
    _, source_id = activity_id.split(":", 1)
    a = Activity(
        activity_id=activity_id,
        source="garmin",
        source_id=source_id,
        start_utc="2026-08-28T12:00:00Z",
        local_date="2026-08-28",
        sport="other",
        sub_sport="bjj",
    )
    db_module.upsert(conn, "activities", a.to_row(), ["source", "source_id"])


class TestActivityLap:
    def test_round_trip(self, conn: sqlite3.Connection) -> None:
        _insert_parent_activity(conn)
        lap = ActivityLap(
            activity_id="garmin:123",
            lap_index=2,
            start_utc="2026-08-28T12:19:20Z",
            duration_s=15.731,
            avg_hr=73,
            max_hr=77,
            intensity_type="ACTIVE",
        )
        db_module.upsert(conn, "activity_laps", lap.to_row(), ["activity_id", "lap_index"])
        row = conn.execute(
            "SELECT * FROM activity_laps WHERE activity_id = ? AND lap_index = ?",
            ("garmin:123", 2),
        ).fetchone()
        reloaded = ActivityLap.from_row(row)
        assert reloaded.avg_hr == 73
        assert reloaded.max_hr == 77
        assert reloaded.intensity_type == "ACTIVE"
        assert reloaded.start_utc == "2026-08-28T12:19:20Z"

    def test_unique_on_activity_and_lap_index_upserts_not_duplicates(
        self, conn: sqlite3.Connection
    ) -> None:
        _insert_parent_activity(conn)
        lap = ActivityLap(activity_id="garmin:123", lap_index=1, start_utc="2026-08-28T12:00:00Z")
        db_module.upsert(conn, "activity_laps", lap.to_row(), ["activity_id", "lap_index"])
        updated = ActivityLap(
            activity_id="garmin:123", lap_index=1, start_utc="2026-08-28T12:00:00Z", avg_hr=99
        )
        db_module.upsert(conn, "activity_laps", updated.to_row(), ["activity_id", "lap_index"])
        rows = conn.execute(
            "SELECT * FROM activity_laps WHERE activity_id = ?", ("garmin:123",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["avg_hr"] == 99

    def test_rejects_lap_referencing_unknown_activity(self, conn: sqlite3.Connection) -> None:
        lap = ActivityLap(
            activity_id="garmin:does-not-exist", lap_index=1, start_utc="2026-08-28T12:00:00Z"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_module.upsert(conn, "activity_laps", lap.to_row(), ["activity_id", "lap_index"])


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


class TestMergeSubjectiveLogEntry:
    def test_hooper_index_computed_when_four_scores_logged_across_separate_calls(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real bug found 2026-08-28: log_wellness.py's own documented usage
        # pattern is logging different subsets on different calls -- without
        # merging first, hooper_index stays permanently NULL even though all
        # 4 sub-scores end up correctly stored in the DB.
        first = SubjectiveLogEntry(date="2026-08-27", sleep_quality=3, stress=2)
        assert first.hooper_index is None
        db_module.upsert(conn, "subjective_log", first.to_row(), ["date"])

        second = SubjectiveLogEntry(date="2026-08-27", fatigue=4, muscle_soreness=5)
        assert second.hooper_index is None  # correct in isolation -- 2 of 4 known
        merged = merge_subjective_log_entry(conn, second)
        assert merged.hooper_index == 14  # 3+2+4+5, computed over the FULL set
        assert merged.sleep_quality == 3  # carried over from the existing row
        assert merged.stress == 2

        db_module.upsert(conn, "subjective_log", merged.to_row(), ["date"])
        row = conn.execute(
            "SELECT * FROM subjective_log WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        assert row["hooper_index"] == 14

    def test_new_value_overrides_existing_on_same_field(self, conn: sqlite3.Connection) -> None:
        first = SubjectiveLogEntry(date="2026-08-27", protein_hit=False)
        db_module.upsert(conn, "subjective_log", first.to_row(), ["date"])

        second = SubjectiveLogEntry(date="2026-08-27", protein_hit=True)
        merged = merge_subjective_log_entry(conn, second)
        assert merged.protein_hit is True

    def test_no_existing_row_returns_entry_unchanged(self, conn: sqlite3.Connection) -> None:
        entry = SubjectiveLogEntry(date="2026-08-27", sleep_quality=3)
        merged = merge_subjective_log_entry(conn, entry)
        assert merged is entry


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
            metric_name="tsb",
            value=12.5,
            unit="load units",
            window_days=42,
            n_days=42,
            confidence="full",
            inputs={"ctl": 120.0, "atl": 107.5},
        )
        db_module.upsert(
            conn, "derived_daily", m.to_row(), ["date", "metric_name"], touch_column=None
        )
        row = conn.execute(
            "SELECT * FROM derived_daily WHERE date = ? AND metric_name = ?", ("2026-08-27", "tsb")
        ).fetchone()
        reloaded = DerivedMetric.from_row(row)
        assert reloaded.value == 12.5
        assert reloaded.inputs == {"ctl": 120.0, "atl": 107.5}


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
