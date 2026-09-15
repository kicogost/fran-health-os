from __future__ import annotations

import sqlite3

import pytest

from health_os.api import log as log_api

_CONFIG = {
    "comp_prep": {
        "strength_sessions": {
            "strength_a": {"exercises": ["pull-ups: 4x5", "push-ups: 3x8"]},
        }
    }
}


class TestBjjLog:
    def test_get_existing_returns_none_when_absent(self, conn: sqlite3.Connection) -> None:
        assert log_api.get_existing_bjj(conn, "2026-08-24", "class") is None

    def test_save_then_get_existing_round_trips(self, conn: sqlite3.Connection) -> None:
        req = log_api.BjjSessionRequest(
            date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
        )
        session = log_api.save_bjj(conn, req)
        assert session.computed_load == 630.0
        existing = log_api.get_existing_bjj(conn, "2026-08-24", "class")
        assert existing["duration_min"] == 90
        assert existing["computed_load"] == 630.0

    def test_invalid_session_type_raises_value_error(self, conn: sqlite3.Connection) -> None:
        req = log_api.BjjSessionRequest(
            date="2026-08-24", session_type="sparring", duration_min=90, session_rpe=7
        )
        with pytest.raises(ValueError, match="session_type"):
            log_api.save_bjj(conn, req)

    def test_upsert_on_same_date_and_type_overwrites(self, conn: sqlite3.Connection) -> None:
        log_api.save_bjj(
            conn,
            log_api.BjjSessionRequest(
                date="2026-08-24", session_type="class", duration_min=60, session_rpe=5
            ),
        )
        log_api.save_bjj(
            conn,
            log_api.BjjSessionRequest(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
            ),
        )
        rows = conn.execute(
            "SELECT * FROM bjj_sessions WHERE date = ? AND session_type = ?",
            ("2026-08-24", "class"),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["duration_min"] == 90


class TestWellnessLog:
    def test_hooper_index_computed_across_separate_calls(self, conn: sqlite3.Connection) -> None:
        # Real bug fixed earlier this session (merge_subjective_log_entry) --
        # the API layer must actually use that merge, not just construct the
        # dataclass directly, or this regresses.
        log_api.save_wellness(
            conn, log_api.WellnessRequest(date="2026-08-24", sleep_quality=3, stress=2)
        )
        log_api.save_wellness(
            conn, log_api.WellnessRequest(date="2026-08-24", fatigue=4, muscle_soreness=5)
        )
        row = conn.execute(
            "SELECT * FROM subjective_log WHERE date = ?", ("2026-08-24",)
        ).fetchone()
        assert row["hooper_index"] == 14

    def test_out_of_range_score_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            log_api.save_wellness(conn, log_api.WellnessRequest(date="2026-08-24", stress=11))


class TestWaistLog:
    def test_save_then_get_existing(self, conn: sqlite3.Connection) -> None:
        log_api.save_waist(conn, log_api.WaistRequest(date="2026-08-24", value_cm=86.0))
        existing = log_api.get_existing_waist(conn, "2026-08-24")
        assert existing["value_cm"] == 86.0

    def test_out_of_range_value_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            log_api.save_waist(conn, log_api.WaistRequest(date="2026-08-24", value_cm=8.0))


class TestCalisthenicsLog:
    def test_save_with_exercises_round_trips(self, conn: sqlite3.Connection) -> None:
        req = log_api.CalisthenicsRequest(
            date="2026-08-24",
            session_type="strength_a",
            session_rpe=6,
            exercises=[log_api.ExerciseEntry(exercise="pull-ups", sets=4, reps=5)],
        )
        session = log_api.save_calisthenics(conn, req)
        assert session.exercises[0]["exercise"] == "pull-ups"
        existing = log_api.get_existing_calisthenics(conn, "2026-08-24", "strength_a")
        assert existing["session_rpe"] == 6

    def test_prescribed_exercises_from_config(self) -> None:
        assert log_api.prescribed_exercises(_CONFIG, "strength_a") == [
            "pull-ups: 4x5",
            "push-ups: 3x8",
        ]

    def test_prescribed_exercises_empty_for_unknown_type(self) -> None:
        assert log_api.prescribed_exercises(_CONFIG, "strength_z") == []

    def test_save_with_duration_computes_load(self, conn: sqlite3.Connection) -> None:
        # Real case: Francisco's 2026-09-13 strength_a session -- 12min @
        # RPE 7 -> Foster's-method load of 84.
        req = log_api.CalisthenicsRequest(
            date="2026-09-13", session_type="strength_a", duration_min=12, session_rpe=7
        )
        session = log_api.save_calisthenics(conn, req)
        assert session.computed_load == 84.0
        existing = log_api.get_existing_calisthenics(conn, "2026-09-13", "strength_a")
        assert existing["duration_min"] == 12
        assert existing["computed_load"] == 84.0

    def test_duration_omitted_leaves_computed_load_none(self, conn: sqlite3.Connection) -> None:
        req = log_api.CalisthenicsRequest(
            date="2026-08-24", session_type="strength_a", session_rpe=6
        )
        session = log_api.save_calisthenics(conn, req)
        assert session.computed_load is None


class TestIllnessLog:
    def test_get_existing_returns_none_when_absent(self, conn: sqlite3.Connection) -> None:
        assert log_api.get_existing_illness(conn, "2026-09-04") is None

    def test_save_then_get_existing_round_trips(self, conn: sqlite3.Connection) -> None:
        req = log_api.IllnessRequest(
            date="2026-09-04",
            sore_throat=True,
            fatigue_weakness=True,
            fever=False,
            congestion=True,
            likely_cause="unclear -- possibly allergies",
            notes="traveling",
        )
        entry = log_api.save_illness(conn, req)
        assert entry.sore_throat is True
        assert entry.fever is False
        assert entry.cough is None
        existing = log_api.get_existing_illness(conn, "2026-09-04")
        assert existing["severity"] is None

        row = conn.execute("SELECT * FROM illness_log WHERE date = ?", ("2026-09-04",)).fetchone()
        assert row["sore_throat"] == 1
        assert row["fever"] == 0
        assert row["cough"] is None

    def test_out_of_range_severity_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            log_api.save_illness(conn, log_api.IllnessRequest(date="2026-09-04", severity=11))

    def test_upsert_on_same_date_overwrites(self, conn: sqlite3.Connection) -> None:
        log_api.save_illness(conn, log_api.IllnessRequest(date="2026-09-04", severity=7))
        log_api.save_illness(conn, log_api.IllnessRequest(date="2026-09-04", severity=3))
        rows = conn.execute("SELECT * FROM illness_log WHERE date = ?", ("2026-09-04",)).fetchall()
        assert len(rows) == 1
        assert rows[0]["severity"] == 3


# ============================================================
# Health History (2026-09-14) -- bloodwork, medical events, medications/
# supplements, allergies, family medical history.
# ============================================================


class TestBloodworkLog:
    def test_save_assigns_an_id(self, conn: sqlite3.Connection) -> None:
        req = log_api.BloodworkRequest(date="2026-09-14", test_name="ferritin", value=85.0)
        result = log_api.save_bloodwork(conn, req)
        assert result.id is not None
        assert result.id > 0

    def test_list_all_with_no_filter_returns_every_row(self, conn: sqlite3.Connection) -> None:
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-03-01", test_name="ferritin", value=70.0)
        )
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-09-14", test_name="ferritin", value=85.0)
        )
        results = log_api.list_bloodwork(conn)
        assert len(results) == 2

    def test_list_by_test_name_returns_history_in_date_order(
        self, conn: sqlite3.Connection
    ) -> None:
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-09-14", test_name="ferritin", value=85.0)
        )
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-03-01", test_name="ferritin", value=70.0)
        )
        log_api.save_bloodwork(
            conn,
            log_api.BloodworkRequest(date="2026-03-01", test_name="total_testosterone", value=18.5),
        )
        history = log_api.list_bloodwork(conn, test_name="ferritin")
        assert [r.date for r in history] == ["2026-03-01", "2026-09-14"]
        assert all(r.test_name == "ferritin" for r in history)

    def test_list_by_date_returns_the_full_panel(self, conn: sqlite3.Connection) -> None:
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-09-14", test_name="ferritin", value=85.0)
        )
        log_api.save_bloodwork(
            conn,
            log_api.BloodworkRequest(date="2026-09-14", test_name="total_testosterone", value=18.5),
        )
        log_api.save_bloodwork(
            conn, log_api.BloodworkRequest(date="2026-03-01", test_name="ferritin", value=70.0)
        )
        panel = log_api.list_bloodwork(conn, date="2026-09-14")
        assert {r.test_name for r in panel} == {"ferritin", "total_testosterone"}

    def test_repeated_saves_never_overwrite_real_gap_this_avoids(
        self, conn: sqlite3.Connection
    ) -> None:
        # No natural key by design (migration 0009) -- a second draw for the
        # SAME test on the SAME date must stay two rows, not silently merge.
        req = log_api.BloodworkRequest(date="2026-09-14", test_name="ferritin", value=85.0)
        log_api.save_bloodwork(conn, req)
        log_api.save_bloodwork(conn, req)
        rows = conn.execute("SELECT * FROM bloodwork_results").fetchall()
        assert len(rows) == 2

    def test_out_of_range_reference_range_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="reference_range_low"):
            log_api.save_bloodwork(
                conn,
                log_api.BloodworkRequest(
                    date="2026-09-14",
                    test_name="ferritin",
                    value=85.0,
                    reference_range_low=400.0,
                    reference_range_high=30.0,
                ),
            )


class TestMedicalEventsLog:
    def test_save_and_list(self, conn: sqlite3.Connection) -> None:
        log_api.save_medical_event(
            conn,
            log_api.MedicalEventRequest(
                date="2018-03-01", category="injury", title="Right knee ACL tear", status="ongoing"
            ),
        )
        events = log_api.list_medical_events(conn)
        assert len(events) == 1
        assert events[0].category == "injury"
        assert events[0].status == "ongoing"

    def test_same_date_twice_is_two_rows_not_an_upsert(self, conn: sqlite3.Connection) -> None:
        req = log_api.MedicalEventRequest(
            date="2026-09-14", category="condition", title="x", status="unknown"
        )
        log_api.save_medical_event(conn, req)
        log_api.save_medical_event(conn, req)
        assert len(log_api.list_medical_events(conn)) == 2

    def test_invalid_category_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="category"):
            log_api.save_medical_event(
                conn,
                log_api.MedicalEventRequest(
                    date="2026-09-14", category="bogus", title="x", status="ongoing"
                ),
            )

    def test_resolved_date_without_resolved_status_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="resolved_date"):
            log_api.save_medical_event(
                conn,
                log_api.MedicalEventRequest(
                    date="2026-09-14",
                    category="injury",
                    title="x",
                    status="ongoing",
                    resolved_date="2026-09-15",
                ),
            )


class TestMedicationsLog:
    def test_save_and_list_ongoing(self, conn: sqlite3.Connection) -> None:
        log_api.save_medication(
            conn,
            log_api.MedicationRequest(
                name="Vitamin D3", type="supplement", start_date="2026-01-01", dosage="2000 IU"
            ),
        )
        meds = log_api.list_medications(conn)
        assert len(meds) == 1
        assert meds[0].end_date is None

    def test_invalid_type_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="type"):
            log_api.save_medication(
                conn, log_api.MedicationRequest(name="x", type="bogus", start_date="2026-09-14")
            )

    def test_restarted_course_is_two_rows(self, conn: sqlite3.Connection) -> None:
        log_api.save_medication(
            conn,
            log_api.MedicationRequest(
                name="Amoxicillin",
                type="medication",
                start_date="2025-01-01",
                end_date="2025-01-10",
            ),
        )
        log_api.save_medication(
            conn,
            log_api.MedicationRequest(
                name="Amoxicillin", type="medication", start_date="2026-06-01"
            ),
        )
        assert len(log_api.list_medications(conn)) == 2


class TestAllergiesLog:
    def test_get_existing_returns_none_when_absent(self, conn: sqlite3.Connection) -> None:
        assert log_api.get_existing_allergy(conn, "peanuts") is None

    def test_save_then_get_existing_and_list(self, conn: sqlite3.Connection) -> None:
        log_api.save_allergy(
            conn, log_api.AllergyRequest(allergen="peanuts", severity="moderate", reaction="hives")
        )
        existing = log_api.get_existing_allergy(conn, "peanuts")
        assert existing["severity"] == "moderate"
        allergies = log_api.list_allergies(conn)
        assert len(allergies) == 1
        assert allergies[0].reaction == "hives"

    def test_upsert_on_allergen_overwrites_not_duplicates(self, conn: sqlite3.Connection) -> None:
        log_api.save_allergy(conn, log_api.AllergyRequest(allergen="peanuts", severity="mild"))
        log_api.save_allergy(conn, log_api.AllergyRequest(allergen="peanuts", severity="severe"))
        rows = conn.execute("SELECT * FROM allergies").fetchall()
        assert len(rows) == 1
        assert rows[0]["severity"] == "severe"

    def test_invalid_severity_raises(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError, match="severity"):
            log_api.save_allergy(
                conn, log_api.AllergyRequest(allergen="peanuts", severity="catastrophic")
            )


class TestFamilyHistoryLog:
    def test_get_existing_returns_none_when_absent(self, conn: sqlite3.Connection) -> None:
        assert log_api.get_existing_family_history(conn, "mother", "asthma") is None

    def test_save_then_get_existing_and_list(self, conn: sqlite3.Connection) -> None:
        log_api.save_family_history(
            conn, log_api.FamilyHistoryRequest(relation="mother", condition="asthma", notes="mild")
        )
        existing = log_api.get_existing_family_history(conn, "mother", "asthma")
        assert existing["notes"] == "mild"
        entries = log_api.list_family_history(conn)
        assert len(entries) == 1

    def test_upsert_on_relation_and_condition_overwrites_not_duplicates(
        self, conn: sqlite3.Connection
    ) -> None:
        log_api.save_family_history(
            conn, log_api.FamilyHistoryRequest(relation="mother", condition="asthma", notes="mild")
        )
        log_api.save_family_history(
            conn,
            log_api.FamilyHistoryRequest(relation="mother", condition="asthma", notes="severe"),
        )
        rows = conn.execute("SELECT * FROM family_medical_history").fetchall()
        assert len(rows) == 1
        assert rows[0]["notes"] == "severe"
