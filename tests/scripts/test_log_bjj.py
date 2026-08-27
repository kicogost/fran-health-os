from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_bjj  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        date=None,
        session_type=None,
        duration=None,
        rpe=None,
        rounds=None,
        gassed=None,
        niggles=None,
        notes=None,
        db_path=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveSessionFlagMode:
    def test_builds_session_from_flags(self) -> None:
        session = log_bjj.resolve_session(
            _args(
                date="2026-08-27", session_type="class", duration=90, rpe=7, rounds=6, gassed=True
            )
        )
        assert session.date == "2026-08-27"
        assert session.session_type == "class"
        assert session.duration_min == 90
        assert session.session_rpe == 7
        assert session.rounds_rolled == 6
        assert session.gassed is True
        assert session.computed_load == 630.0

    def test_defaults_date_to_today_madrid(self) -> None:
        session = log_bjj.resolve_session(_args(session_type="open_mat", duration=120, rpe=9))
        assert session.date == log_bjj._today_madrid()

    def test_gassed_defaults_false_when_unset(self) -> None:
        session = log_bjj.resolve_session(_args(session_type="class", duration=90, rpe=5))
        assert session.gassed is False

    def test_missing_required_flag_raises(self) -> None:
        with pytest.raises(SystemExit, match="--rpe"):
            log_bjj.resolve_session(_args(session_type="class", duration=90))

    def test_invalid_session_type_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            log_bjj.resolve_session(_args(session_type="sparring", duration=90, rpe=7))
        # argparse's choices= would normally catch this before resolve_session ever
        # sees it in real use — this exercises BjjSession's own validation directly.


class TestResolveSessionInteractiveMode:
    def test_prompts_for_every_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(
            ["2026-08-27", "open_mat", "120", "9", "8", "y", "left knee", "worked passing"]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        session = log_bjj.resolve_session(_args())
        assert session.date == "2026-08-27"
        assert session.session_type == "open_mat"
        assert session.duration_min == 120
        assert session.session_rpe == 9
        assert session.rounds_rolled == 8
        assert session.gassed is True
        assert session.niggles == "left knee"
        assert session.notes == "worked passing"

    def test_optional_fields_blank_become_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-27", "class", "90", "7", "", "n", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        session = log_bjj.resolve_session(_args())
        assert session.rounds_rolled is None
        assert session.niggles is None
        assert session.notes is None

    def test_rejects_invalid_choice_until_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-27", "sparring", "class", "90", "7", "", "n", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        session = log_bjj.resolve_session(_args())
        assert session.session_type == "class"


class TestMainEndToEnd:
    def test_logs_a_new_session(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_bjj.main(
            ["--type", "class", "--duration", "90", "--rpe", "7", "--db-path", str(db_path)]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bjj_sessions").fetchone()
        conn.close()

        assert row["duration_min"] == 90
        assert row["session_rpe"] == 7
        assert row["computed_load"] == 630.0

        out = capsys.readouterr().out
        assert "load 630" in out

    def test_reupserting_same_date_type_updates_not_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-27", "--type", "class", "--db-path", str(db_path)]
        log_bjj.main([*common, "--duration", "90", "--rpe", "7"])
        capsys.readouterr()  # discard first run's output
        rc = log_bjj.main([*common, "--duration", "60", "--rpe", "5"])
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM bjj_sessions").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["duration_min"] == 60
        assert rows[0]["computed_load"] == 300.0

        out = capsys.readouterr().out
        assert "Updating existing class session" in out

    def test_different_session_type_same_date_is_a_separate_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = [
            "--date",
            "2026-08-27",
            "--duration",
            "60",
            "--rpe",
            "6",
            "--db-path",
            str(db_path),
        ]
        log_bjj.main([*common, "--type", "class"])
        log_bjj.main([*common, "--type", "gi_drilling"])

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT session_type FROM bjj_sessions ORDER BY session_type"
        ).fetchall()
        conn.close()

        assert [r[0] for r in rows] == ["class", "gi_drilling"]
