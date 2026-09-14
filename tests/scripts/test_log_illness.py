from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_illness  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        date=None,
        severity=None,
        sore_throat=None,
        fever=None,
        temperature_c=None,
        congestion=None,
        cough=None,
        body_aches=None,
        fatigue_weakness=None,
        headache=None,
        likely_cause=None,
        notes=None,
        db_path=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveEntryFlagMode:
    def test_symptom_flags_set_correctly(self) -> None:
        entry = log_illness.resolve_entry(
            _args(
                date="2026-09-04",
                sore_throat=True,
                fatigue_weakness=True,
                fever=False,
                congestion=True,
            )
        )
        assert entry.sore_throat is True
        assert entry.fatigue_weakness is True
        assert entry.fever is False
        assert entry.congestion is True
        # Never mentioned -> stays None, not invented.
        assert entry.cough is None
        assert entry.body_aches is None
        assert entry.headache is None
        assert entry.severity is None

    def test_just_notes_is_flag_mode_not_interactive(self) -> None:
        entry = log_illness.resolve_entry(_args(date="2026-09-04", notes="just a note"))
        assert entry.notes == "just a note"
        assert entry.sore_throat is None

    def test_defaults_date_to_today_madrid(self) -> None:
        entry = log_illness.resolve_entry(_args(sore_throat=True))
        assert entry.date == log_illness._today_madrid()

    def test_out_of_range_severity_raises(self) -> None:
        with pytest.raises(ValueError):
            log_illness.resolve_entry(_args(date="2026-09-04", severity=11))

    def test_temperature_and_likely_cause_round_trip(self) -> None:
        entry = log_illness.resolve_entry(
            _args(date="2026-09-04", temperature_c=37.8, likely_cause="viral")
        )
        assert entry.temperature_c == 37.8
        assert entry.likely_cause == "viral"


class TestResolveEntryInteractiveMode:
    def test_no_flags_at_all_triggers_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(
            [
                "2026-09-04",  # date
                "5",  # severity
                "y",  # sore throat
                "n",  # fever
                "37.8",  # temperature
                "y",  # congestion
                "",  # cough (skip)
                "",  # body aches (skip)
                "y",  # fatigue/weakness
                "",  # headache (skip)
                "allergies",  # likely cause
                "some notes",  # notes
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        entry = log_illness.resolve_entry(_args())
        assert entry.date == "2026-09-04"
        assert entry.severity == 5
        assert entry.sore_throat is True
        assert entry.fever is False
        assert entry.temperature_c == 37.8
        assert entry.congestion is True
        assert entry.cough is None
        assert entry.body_aches is None
        assert entry.fatigue_weakness is True
        assert entry.headache is None
        assert entry.likely_cause == "allergies"
        assert entry.notes == "some notes"

    def test_blank_answers_all_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-09-04", "", "", "", "", "", "", "", "", "", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        entry = log_illness.resolve_entry(_args())
        assert entry.severity is None
        assert entry.sore_throat is None
        assert entry.temperature_c is None
        assert entry.likely_cause is None
        assert entry.notes is None


class TestMainEndToEnd:
    def test_logs_a_new_entry(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_illness.main(
            [
                "--date",
                "2026-09-04",
                "--sore-throat",
                "--fatigue-weakness",
                "--no-fever",
                "--congestion",
                "--likely-cause",
                "unclear -- possibly allergies",
                "--notes",
                "traveling",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM illness_log").fetchone()
        conn.close()

        assert row["sore_throat"] == 1
        assert row["fatigue_weakness"] == 1
        assert row["fever"] == 0
        assert row["congestion"] == 1
        assert row["cough"] is None
        assert row["severity"] is None
        assert row["likely_cause"] == "unclear -- possibly allergies"
        assert "Logged: 2026-09-04" in capsys.readouterr().out

    def test_reupserting_same_date_updates_not_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-09-04", "--db-path", str(db_path)]
        log_illness.main([*common, "--severity", "7"])
        capsys.readouterr()
        rc = log_illness.main([*common, "--severity", "3"])
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM illness_log").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["severity"] == 3
        assert "Updating existing entry" in capsys.readouterr().out

    def test_out_of_range_severity_via_cli_returns_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        rc = log_illness.main(
            ["--date", "2026-09-04", "--severity", "11", "--db-path", str(db_path)]
        )
        assert rc == 1
