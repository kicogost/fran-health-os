from __future__ import annotations

import sqlite3

import pytest

from health_os.core import db as db_module
from health_os.core.models import (
    Activity,
    ActivityLap,
    Allergy,
    BjjSession,
    BloodworkResult,
    BodyMeasurement,
    CalisthenicsSession,
    DailyMetric,
    DerivedMetric,
    FamilyMedicalHistory,
    IllnessLog,
    IngestRun,
    MedicalEvent,
    MedicationSupplement,
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

    def test_renpho_body_composition_fields_omitted_when_none(self) -> None:
        # Migration 0007 -- these fields must follow the exact same
        # partial-upsert-doesn't-clobber convention as every other optional
        # DailyMetric field (design principle 6 / the module's own docstring).
        m = DailyMetric(date="2026-09-01", weight_kg=83.75, body_fat_pct=26.4)
        row = m.to_row()
        assert row == {"date": "2026-09-01", "weight_kg": 83.75, "body_fat_pct": 26.4}

    def test_renpho_body_composition_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        m = DailyMetric(
            date="2026-09-01",
            weight_kg=83.75,
            bmi=26.9,
            body_fat_pct=26.4,
            skeletal_muscle_pct=47.4,
            lean_body_mass_kg=61.64,
            subcutaneous_fat_pct=23.3,
            visceral_fat_rating=10,
            body_water_pct=53.1,
            muscle_mass_kg=58.54,
            bone_mass_kg=3.10,
            protein_pct=16.8,
            bmr_kcal=1708,
            metabolic_age=26,
            sources={"weight_kg": "renpho_csv", "bmi": "renpho_csv"},
        )
        db_module.upsert(conn, "daily_metrics", m.to_row(), ["date"])
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-09-01",)).fetchone()
        reloaded = DailyMetric.from_row(row)
        assert reloaded.body_fat_pct == pytest.approx(26.4)
        assert reloaded.skeletal_muscle_pct == pytest.approx(47.4)
        assert reloaded.lean_body_mass_kg == pytest.approx(61.64)
        assert reloaded.subcutaneous_fat_pct == pytest.approx(23.3)
        assert reloaded.visceral_fat_rating == 10
        assert reloaded.body_water_pct == pytest.approx(53.1)
        assert reloaded.muscle_mass_kg == pytest.approx(58.54)
        assert reloaded.bone_mass_kg == pytest.approx(3.10)
        assert reloaded.protein_pct == pytest.approx(16.8)
        assert reloaded.bmr_kcal == 1708
        assert reloaded.metabolic_age == 26


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

    def test_computed_load_uses_fosters_method_real_session(self) -> None:
        # Francisco's real 2026-09-13 strength_a session: 100 push-ups
        # (10x10), ~10-15 min stated -- logged with duration_min=12,
        # session_rpe=7 -> 12 * 7 = 84.
        s = CalisthenicsSession(
            date="2026-09-13", session_type="strength_a", duration_min=12, session_rpe=7
        )
        assert s.computed_load == 84.0

    def test_computed_load_uses_fosters_method_synthetic(self) -> None:
        s = CalisthenicsSession(
            date="2026-08-24", session_type="strength_b", duration_min=45, session_rpe=6
        )
        assert s.computed_load == 270.0

    def test_explicit_computed_load_not_overwritten(self) -> None:
        s = CalisthenicsSession(
            date="2026-08-24",
            session_type="strength_a",
            duration_min=45,
            session_rpe=6,
            computed_load=500.0,
        )
        assert s.computed_load == 500.0

    def test_computed_load_none_when_duration_missing(self) -> None:
        s = CalisthenicsSession(date="2026-08-24", session_type="strength_a", session_rpe=6)
        assert s.computed_load is None

    def test_computed_load_none_when_rpe_missing(self) -> None:
        s = CalisthenicsSession(date="2026-08-24", session_type="strength_a", duration_min=45)
        assert s.computed_load is None

    def test_rejects_non_positive_duration(self) -> None:
        with pytest.raises(ValueError, match="duration_min"):
            CalisthenicsSession(date="2026-08-24", session_type="strength_a", duration_min=0)

    def test_round_trip_duration_and_computed_load(self, conn: sqlite3.Connection) -> None:
        s = CalisthenicsSession(
            date="2026-09-13", session_type="strength_a", duration_min=12, session_rpe=7
        )
        db_module.upsert(conn, "calisthenics_sessions", s.to_row(), ["date", "session_type"])
        row = conn.execute(
            "SELECT * FROM calisthenics_sessions WHERE date = ? AND session_type = ?",
            ("2026-09-13", "strength_a"),
        ).fetchone()
        reloaded = CalisthenicsSession.from_row(row)
        assert reloaded.duration_min == 12
        assert reloaded.computed_load == 84.0


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

    def test_rejects_out_of_range_value_cm_too_low(self) -> None:
        with pytest.raises(ValueError):
            BodyMeasurement(date="2026-08-30", value_cm=39.9)

    def test_rejects_out_of_range_value_cm_too_high(self) -> None:
        with pytest.raises(ValueError):
            BodyMeasurement(date="2026-08-30", value_cm=200.1)

    def test_accepts_value_cm_at_range_boundaries(self) -> None:
        low = BodyMeasurement(date="2026-08-30", value_cm=40.0)
        high = BodyMeasurement(date="2026-08-30", value_cm=200.0)
        assert low.value_cm == 40.0
        assert high.value_cm == 200.0


class TestIllnessLog:
    def test_to_row_omits_none_by_default(self) -> None:
        entry = IllnessLog(date="2026-09-04", sore_throat=True)
        row = entry.to_row()
        assert row == {"date": "2026-09-04", "sore_throat": 1}

    def test_round_trip_booleans_and_partial_fields(self, conn: sqlite3.Connection) -> None:
        entry = IllnessLog(
            date="2026-09-04",
            sore_throat=True,
            fatigue_weakness=True,
            fever=False,
            congestion=True,
            likely_cause="unclear -- possibly allergies",
            notes="traveling, unfamiliar bed",
        )
        db_module.upsert(conn, "illness_log", entry.to_row(), ["date"])
        row = conn.execute("SELECT * FROM illness_log WHERE date = ?", ("2026-09-04",)).fetchone()
        reloaded = IllnessLog.from_row(row)
        assert reloaded.sore_throat is True
        assert reloaded.fatigue_weakness is True
        assert reloaded.fever is False
        assert reloaded.congestion is True
        # Never mentioned -> stays None, not invented as False (design principle 6).
        assert reloaded.cough is None
        assert reloaded.body_aches is None
        assert reloaded.headache is None
        assert reloaded.severity is None
        assert reloaded.temperature_c is None
        assert reloaded.likely_cause == "unclear -- possibly allergies"
        assert reloaded.notes == "traveling, unfamiliar bed"

    def test_round_trip_temperature_and_severity(self, conn: sqlite3.Connection) -> None:
        entry = IllnessLog(date="2026-09-04", severity=6, temperature_c=37.8)
        db_module.upsert(conn, "illness_log", entry.to_row(), ["date"])
        row = conn.execute("SELECT * FROM illness_log WHERE date = ?", ("2026-09-04",)).fetchone()
        reloaded = IllnessLog.from_row(row)
        assert reloaded.severity == 6
        assert reloaded.temperature_c == 37.8

    def test_rejects_out_of_range_severity(self) -> None:
        with pytest.raises(ValueError):
            IllnessLog(date="2026-09-04", severity=11)

    def test_rejects_zero_severity(self) -> None:
        with pytest.raises(ValueError):
            IllnessLog(date="2026-09-04", severity=0)

    def test_accepts_severity_at_boundaries(self) -> None:
        low = IllnessLog(date="2026-09-04", severity=1)
        high = IllnessLog(date="2026-09-04", severity=10)
        assert low.severity == 1
        assert high.severity == 10

    def test_all_fields_none_when_only_date_given(self, conn: sqlite3.Connection) -> None:
        entry = IllnessLog(date="2026-09-04")
        db_module.upsert(conn, "illness_log", entry.to_row(), ["date"])
        row = conn.execute("SELECT * FROM illness_log WHERE date = ?", ("2026-09-04",)).fetchone()
        reloaded = IllnessLog.from_row(row)
        assert reloaded.severity is None
        assert reloaded.sore_throat is None
        assert reloaded.fever is None
        assert reloaded.temperature_c is None
        assert reloaded.congestion is None
        assert reloaded.cough is None
        assert reloaded.body_aches is None
        assert reloaded.fatigue_weakness is None
        assert reloaded.headache is None
        assert reloaded.likely_cause is None
        assert reloaded.notes is None


class TestBloodworkResult:
    def test_to_row_omits_none_by_default(self) -> None:
        result = BloodworkResult(date="2026-09-14", test_name="ferritin", value=85.0)
        row = result.to_row()
        assert row == {"date": "2026-09-14", "test_name": "ferritin", "value": 85.0}

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        result = BloodworkResult(
            date="2026-09-14",
            test_name="total_testosterone",
            value=18.5,
            unit="nmol/L",
            reference_range_low=8.6,
            reference_range_high=29.0,
            notes="fasted draw",
        )
        new_id = db_module.insert(conn, "bloodwork_results", result.to_row())
        row = conn.execute("SELECT * FROM bloodwork_results WHERE id = ?", (new_id,)).fetchone()
        reloaded = BloodworkResult.from_row(row)
        assert reloaded.test_name == "total_testosterone"
        assert reloaded.value == 18.5
        assert reloaded.unit == "nmol/L"
        assert reloaded.reference_range_low == 8.6
        assert reloaded.reference_range_high == 29.0
        assert reloaded.notes == "fasted draw"

    def test_no_natural_key_two_inserts_stay_two_rows(self, conn: sqlite3.Connection) -> None:
        first = BloodworkResult(date="2026-09-14", test_name="ferritin", value=85.0)
        second = BloodworkResult(date="2026-09-14", test_name="ferritin", value=90.0)
        db_module.insert(conn, "bloodwork_results", first.to_row())
        db_module.insert(conn, "bloodwork_results", second.to_row())
        rows = conn.execute(
            "SELECT * FROM bloodwork_results WHERE test_name = 'ferritin'"
        ).fetchall()
        assert len(rows) == 2

    def test_rejects_inverted_reference_range(self) -> None:
        with pytest.raises(ValueError, match="reference_range_low"):
            BloodworkResult(
                date="2026-09-14",
                test_name="ferritin",
                value=85.0,
                reference_range_low=300.0,
                reference_range_high=30.0,
            )

    def test_one_sided_reference_range_is_valid(self) -> None:
        result = BloodworkResult(
            date="2026-09-14", test_name="ferritin", value=85.0, reference_range_high=300.0
        )
        assert result.reference_range_low is None
        assert result.reference_range_high == 300.0


class TestMedicalEvent:
    def test_to_row_omits_none_by_default(self) -> None:
        event = MedicalEvent(
            date="2018-03-01", category="injury", title="Right knee ACL tear", status="ongoing"
        )
        row = event.to_row()
        assert row == {
            "date": "2018-03-01",
            "category": "injury",
            "title": "Right knee ACL tear",
            "status": "ongoing",
        }

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        event = MedicalEvent(
            date="2018-03-01",
            category="injury",
            title="Right knee ACL tear",
            status="ongoing",
            notes="permanent -- never recommend running",
        )
        new_id = db_module.insert(conn, "medical_events", event.to_row())
        row = conn.execute("SELECT * FROM medical_events WHERE id = ?", (new_id,)).fetchone()
        reloaded = MedicalEvent.from_row(row)
        assert reloaded.category == "injury"
        assert reloaded.status == "ongoing"
        assert reloaded.resolved_date is None
        assert reloaded.notes == "permanent -- never recommend running"

    def test_resolved_event_round_trips_resolved_date(self, conn: sqlite3.Connection) -> None:
        event = MedicalEvent(
            date="2024-01-10",
            category="surgery",
            title="Wisdom teeth removal",
            status="resolved",
            resolved_date="2024-01-24",
        )
        new_id = db_module.insert(conn, "medical_events", event.to_row())
        row = conn.execute("SELECT * FROM medical_events WHERE id = ?", (new_id,)).fetchone()
        reloaded = MedicalEvent.from_row(row)
        assert reloaded.resolved_date == "2024-01-24"

    def test_rejects_invalid_category(self) -> None:
        with pytest.raises(ValueError, match="category"):
            MedicalEvent(date="2026-09-14", category="bogus", title="x", status="ongoing")

    def test_rejects_invalid_status(self) -> None:
        with pytest.raises(ValueError, match="status"):
            MedicalEvent(date="2026-09-14", category="injury", title="x", status="bogus")

    def test_rejects_resolved_date_without_resolved_status(self) -> None:
        with pytest.raises(ValueError, match="resolved_date"):
            MedicalEvent(
                date="2026-09-14",
                category="injury",
                title="x",
                status="ongoing",
                resolved_date="2026-09-15",
            )

    def test_no_natural_key_same_date_twice_is_valid(self, conn: sqlite3.Connection) -> None:
        row = {"date": "2026-09-14", "category": "injury", "title": "x", "status": "ongoing"}
        event = MedicalEvent(**row)
        db_module.insert(conn, "medical_events", event.to_row())
        db_module.insert(conn, "medical_events", event.to_row())
        rows = conn.execute("SELECT * FROM medical_events").fetchall()
        assert len(rows) == 2


class TestMedicationSupplement:
    def test_to_row_omits_none_by_default(self) -> None:
        med = MedicationSupplement(name="Creatine", type="supplement", start_date="2026-09-01")
        row = med.to_row()
        assert row == {"name": "Creatine", "type": "supplement", "start_date": "2026-09-01"}

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        med = MedicationSupplement(
            name="Vitamin D3",
            type="supplement",
            dosage="2000 IU",
            frequency="daily",
            start_date="2026-01-01",
            notes="winter months",
        )
        new_id = db_module.insert(conn, "medications_supplements", med.to_row())
        row = conn.execute(
            "SELECT * FROM medications_supplements WHERE id = ?", (new_id,)
        ).fetchone()
        reloaded = MedicationSupplement.from_row(row)
        assert reloaded.name == "Vitamin D3"
        assert reloaded.dosage == "2000 IU"
        assert reloaded.end_date is None  # still taking it

    def test_end_date_none_means_currently_taking(self) -> None:
        med = MedicationSupplement(name="Vitamin D3", type="supplement", start_date="2026-01-01")
        assert med.end_date is None

    def test_rejects_invalid_type(self) -> None:
        with pytest.raises(ValueError, match="type"):
            MedicationSupplement(name="x", type="bogus", start_date="2026-09-14")

    def test_rejects_end_date_before_start_date(self) -> None:
        with pytest.raises(ValueError, match="end_date"):
            MedicationSupplement(
                name="x", type="medication", start_date="2026-09-14", end_date="2026-09-01"
            )

    def test_no_natural_key_same_name_twice_is_valid(self, conn: sqlite3.Connection) -> None:
        # A real, separate course each time -- started, stopped, restarted.
        first = MedicationSupplement(
            name="Amoxicillin", type="medication", start_date="2025-01-01", end_date="2025-01-10"
        )
        second = MedicationSupplement(
            name="Amoxicillin", type="medication", start_date="2026-06-01"
        )
        db_module.insert(conn, "medications_supplements", first.to_row())
        db_module.insert(conn, "medications_supplements", second.to_row())
        rows = conn.execute(
            "SELECT * FROM medications_supplements WHERE name = 'Amoxicillin'"
        ).fetchall()
        assert len(rows) == 2


class TestAllergy:
    def test_to_row_omits_none_by_default(self) -> None:
        allergy = Allergy(allergen="peanuts")
        assert allergy.to_row() == {"allergen": "peanuts"}

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        allergy = Allergy(
            allergen="peanuts",
            reaction="hives",
            severity="moderate",
            date_identified="2010-05-01",
            notes="confirmed by allergist",
        )
        db_module.upsert(conn, "allergies", allergy.to_row(), ["allergen"])
        row = conn.execute("SELECT * FROM allergies WHERE allergen = ?", ("peanuts",)).fetchone()
        reloaded = Allergy.from_row(row)
        assert reloaded.reaction == "hives"
        assert reloaded.severity == "moderate"
        assert reloaded.date_identified == "2010-05-01"

    def test_rejects_invalid_severity(self) -> None:
        with pytest.raises(ValueError, match="severity"):
            Allergy(allergen="peanuts", severity="catastrophic")

    def test_upsert_on_allergen_overwrites_not_duplicates(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "allergies", Allergy(allergen="peanuts", severity="mild").to_row(), ["allergen"]
        )
        db_module.upsert(
            conn,
            "allergies",
            Allergy(allergen="peanuts", severity="severe").to_row(),
            ["allergen"],
        )
        rows = conn.execute("SELECT * FROM allergies WHERE allergen = 'peanuts'").fetchall()
        assert len(rows) == 1
        assert rows[0]["severity"] == "severe"


class TestFamilyMedicalHistory:
    def test_to_row_omits_none_by_default(self) -> None:
        entry = FamilyMedicalHistory(relation="mother", condition="hypertension")
        assert entry.to_row() == {"relation": "mother", "condition": "hypertension"}

    def test_round_trip_through_db(self, conn: sqlite3.Connection) -> None:
        entry = FamilyMedicalHistory(
            relation="paternal grandfather", condition="type 2 diabetes", notes="diagnosed ~60yo"
        )
        db_module.upsert(conn, "family_medical_history", entry.to_row(), ["relation", "condition"])
        row = conn.execute(
            "SELECT * FROM family_medical_history WHERE relation = ? AND condition = ?",
            ("paternal grandfather", "type 2 diabetes"),
        ).fetchone()
        reloaded = FamilyMedicalHistory.from_row(row)
        assert reloaded.notes == "diagnosed ~60yo"

    def test_upsert_on_relation_and_condition_overwrites_not_duplicates(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "family_medical_history",
            FamilyMedicalHistory(relation="mother", condition="asthma", notes="mild").to_row(),
            ["relation", "condition"],
        )
        db_module.upsert(
            conn,
            "family_medical_history",
            FamilyMedicalHistory(relation="mother", condition="asthma", notes="severe").to_row(),
            ["relation", "condition"],
        )
        rows = conn.execute(
            "SELECT * FROM family_medical_history "
            "WHERE relation = 'mother' AND condition = 'asthma'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["notes"] == "severe"


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
