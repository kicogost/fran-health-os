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
