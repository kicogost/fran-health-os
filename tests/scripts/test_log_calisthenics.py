from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_calisthenics  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(date=None, session_type=None, session_rpe=None, notes=None, db_path=None)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveSessionFlagMode:
    def test_builds_session_from_flags(self) -> None:
        session = log_calisthenics.resolve_session(
            _args(date="2026-08-24", session_type="strength_a", session_rpe=6, notes="felt strong")
        )
        assert session.date == "2026-08-24"
        assert session.session_type == "strength_a"
        assert session.session_rpe == 6
        assert session.notes == "felt strong"
        assert session.exercises is None

    def test_defaults_date_to_today_madrid(self) -> None:
        session = log_calisthenics.resolve_session(_args(session_type="strength_b"))
        assert session.date == log_calisthenics._today_madrid()

    def test_invalid_session_type_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            log_calisthenics.resolve_session(_args(session_type="strength_c"))


class TestResolveSessionInteractiveMode:
    def test_walks_every_prescribed_exercise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            log_calisthenics,
            "_load_prescribed_exercises",
            lambda session_type: ["pull-ups: 4x5", "push-ups: 3x8"],
        )
        answers = iter(
            [
                "2026-08-24",  # date
                "strength_a",  # session type
                "4",  # pull-ups sets
                "5",  # pull-ups reps
                "5.0",  # pull-ups added weight
                "",  # pull-ups notes
                "3",  # push-ups sets
                "8",  # push-ups reps
                "",  # push-ups added weight
                "",  # push-ups notes
                "6",  # session RPE
                "",  # session notes
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        session = log_calisthenics.resolve_session(_args())
        assert session.exercises == [
            {"exercise": "pull-ups", "sets": 4, "reps": 5, "added_weight_kg": 5.0, "notes": None},
            {"exercise": "push-ups", "sets": 3, "reps": 8, "added_weight_kg": None, "notes": None},
        ]
        assert session.session_rpe == 6

    def test_blank_sets_skips_exercise_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            log_calisthenics,
            "_load_prescribed_exercises",
            lambda session_type: ["pull-ups: 4x5", "push-ups: 3x8"],
        )
        answers = iter(
            [
                "2026-08-24",
                "strength_a",
                "",  # pull-ups sets: blank -> skip this exercise
                "3",  # push-ups sets
                "8",
                "",
                "",
                "",  # session RPE
                "",  # session notes
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        session = log_calisthenics.resolve_session(_args())
        assert len(session.exercises) == 1
        assert session.exercises[0]["exercise"] == "push-ups"


class TestExerciseName:
    def test_strips_prescription_after_colon(self) -> None:
        assert (
            log_calisthenics._exercise_name("weighted pull-ups: 4x5 (superset)")
            == "weighted pull-ups"
        )


class TestMainEndToEnd:
    def test_logs_a_new_session(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_calisthenics.main(
            ["--type", "strength_a", "--rpe", "6", "--db-path", str(db_path)]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM calisthenics_sessions").fetchone()
        conn.close()

        assert row["session_type"] == "strength_a"
        assert row["session_rpe"] == 6

        out = capsys.readouterr().out
        assert "Logged:" in out

    def test_reupserting_same_date_type_updates_not_duplicates(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-24", "--type", "strength_a", "--db-path", str(db_path)]
        log_calisthenics.main([*common, "--rpe", "6"])
        log_calisthenics.main([*common, "--rpe", "8"])

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM calisthenics_sessions").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["session_rpe"] == 8

    def test_different_session_type_same_date_is_a_separate_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-24", "--db-path", str(db_path)]
        log_calisthenics.main([*common, "--type", "strength_a"])
        log_calisthenics.main([*common, "--type", "strength_b"])

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT session_type FROM calisthenics_sessions ORDER BY session_type"
        ).fetchall()
        conn.close()

        assert [r[0] for r in rows] == ["strength_a", "strength_b"]
