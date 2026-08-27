from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_measurement  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(date=None, measurement_type=None, value=None, notes=None, db_path=None)
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveMeasurementFlagMode:
    def test_builds_measurement_from_flags(self) -> None:
        m = log_measurement.resolve_measurement(
            _args(date="2026-08-30", value=85.5, notes="post-Block-1")
        )
        assert m.date == "2026-08-30"
        assert m.measurement_type == "waist"
        assert m.value_cm == 85.5
        assert m.notes == "post-Block-1"

    def test_defaults_date_to_today_madrid(self) -> None:
        m = log_measurement.resolve_measurement(_args(value=85.5))
        assert m.date == log_measurement._today_madrid()

    def test_custom_measurement_type(self) -> None:
        m = log_measurement.resolve_measurement(_args(value=40.0, measurement_type="thigh"))
        assert m.measurement_type == "thigh"


class TestResolveMeasurementInteractiveMode:
    def test_prompts_for_every_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-30", "waist", "85.5", "post-Block-1"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        m = log_measurement.resolve_measurement(_args())
        assert m.date == "2026-08-30"
        assert m.value_cm == 85.5
        assert m.notes == "post-Block-1"

    def test_invalid_value_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-30", "waist", "not-a-number"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        with pytest.raises(SystemExit):
            log_measurement.resolve_measurement(_args())


class TestMainEndToEnd:
    def test_logs_a_new_measurement(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_measurement.main(
            ["--value", "85.5", "--date", "2026-08-30", "--db-path", str(db_path)]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM body_measurements").fetchone()
        conn.close()

        assert row["value_cm"] == 85.5
        assert row["measurement_type"] == "waist"
        assert "85.5 cm" in capsys.readouterr().out

    def test_reupserting_same_date_type_updates_not_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-30", "--db-path", str(db_path)]
        log_measurement.main([*common, "--value", "86.0"])
        capsys.readouterr()
        rc = log_measurement.main([*common, "--value", "85.5"])
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM body_measurements").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["value_cm"] == 85.5
        assert "Updating existing waist" in capsys.readouterr().out

    def test_different_measurement_type_same_date_is_separate_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-30", "--db-path", str(db_path)]
        log_measurement.main([*common, "--value", "85.5", "--type", "waist"])
        log_measurement.main([*common, "--value", "58.0", "--type", "thigh"])

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT measurement_type FROM body_measurements ORDER BY measurement_type"
        ).fetchall()
        conn.close()

        assert [r[0] for r in rows] == ["thigh", "waist"]
