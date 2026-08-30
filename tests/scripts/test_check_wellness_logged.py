from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_wellness_logged  # noqa: E402
from health_os.core import db as db_module  # noqa: E402


class TestIsWellnessLogged:
    def test_no_row_at_all_is_not_logged(self, conn: sqlite3.Connection) -> None:
        assert not check_wellness_logged.is_wellness_logged(conn, "2026-08-30")

    def test_all_four_fields_present_is_logged(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "subjective_log",
            {
                "date": "2026-08-30",
                "sleep_quality": 3,
                "stress": 4,
                "fatigue": 5,
                "muscle_soreness": 2,
            },
            ["date"],
        )
        assert check_wellness_logged.is_wellness_logged(conn, "2026-08-30")

    def test_partial_row_missing_one_field_is_not_logged(self, conn: sqlite3.Connection) -> None:
        # Real reason this matters: core.models.SubjectiveLogEntry only
        # computes hooper_index when all four are present -- a partial day
        # can't feed the deload trigger's hooper_sustained_high() check
        # either, so it must count as "not logged" here too, not "3/4 is
        # close enough."
        db_module.upsert(
            conn,
            "subjective_log",
            {"date": "2026-08-30", "sleep_quality": 3, "stress": 4, "fatigue": 5},
            ["date"],
        )
        assert not check_wellness_logged.is_wellness_logged(conn, "2026-08-30")

    def test_a_different_dates_log_does_not_count(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "subjective_log",
            {
                "date": "2026-08-29",
                "sleep_quality": 3,
                "stress": 4,
                "fatigue": 5,
                "muscle_soreness": 2,
            },
            ["date"],
        )
        assert not check_wellness_logged.is_wellness_logged(conn, "2026-08-30")


class TestMain:
    def test_exit_0_when_logged(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        conn = db_module.init_db(str(db_path))
        db_module.upsert(
            conn,
            "subjective_log",
            {
                "date": "2026-08-30",
                "sleep_quality": 3,
                "stress": 4,
                "fatigue": 5,
                "muscle_soreness": 2,
            },
            ["date"],
        )
        conn.close()

        rc = check_wellness_logged.main(["--date", "2026-08-30", "--db-path", str(db_path)])
        assert rc == 0
        assert "already logged" in capsys.readouterr().out

    def test_exit_1_when_not_logged(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        db_module.init_db(str(db_path)).close()

        rc = check_wellness_logged.main(["--date", "2026-08-30", "--db-path", str(db_path)])
        assert rc == 1
        assert "not fully logged" in capsys.readouterr().out
