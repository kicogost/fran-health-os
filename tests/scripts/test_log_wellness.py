from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_wellness  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        date=None,
        sleep_quality=None,
        stress=None,
        fatigue=None,
        muscle_soreness=None,
        protein_hit=None,
        gassed=None,
        social_meal=None,
        felt_note=None,
        niggles=None,
        day_note=None,
        db_path=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveEntryFlagMode:
    def test_all_four_wellness_scores_compute_hooper_index(self) -> None:
        entry = log_wellness.resolve_entry(
            _args(date="2026-08-27", sleep_quality=2, stress=3, fatigue=2, muscle_soreness=4)
        )
        assert entry.hooper_index == 11

    def test_partial_wellness_scores_leave_hooper_index_none(self) -> None:
        entry = log_wellness.resolve_entry(_args(date="2026-08-27", sleep_quality=2, stress=3))
        assert entry.hooper_index is None

    def test_just_protein_hit_is_flag_mode_not_interactive(self) -> None:
        entry = log_wellness.resolve_entry(_args(date="2026-08-27", protein_hit=True))
        assert entry.protein_hit is True
        assert entry.sleep_quality is None

    def test_defaults_date_to_today_madrid(self) -> None:
        entry = log_wellness.resolve_entry(_args(sleep_quality=3))
        assert entry.date == log_wellness._today_madrid()

    def test_out_of_range_score_raises(self) -> None:
        with pytest.raises(ValueError):
            log_wellness.resolve_entry(_args(date="2026-08-27", sleep_quality=11))


class TestResolveEntryInteractiveMode:
    def test_no_flags_at_all_triggers_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-27", "2", "3", "2", "4", "y", "n", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        entry = log_wellness.resolve_entry(_args())
        assert entry.date == "2026-08-27"
        assert entry.hooper_index == 11
        assert entry.protein_hit is True
        assert entry.social_meal is False

    def test_date_only_still_triggers_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # --date alone isn't "content" -- must still prompt, not silently no-op.
        answers = iter(["2026-08-30", "", "", "", "", "", "", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        entry = log_wellness.resolve_entry(_args(date="2026-08-30"))
        assert entry.date == "2026-08-30"
        assert entry.hooper_index is None

    def test_blank_wellness_scores_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["2026-08-27", "", "", "", "", "", "", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        entry = log_wellness.resolve_entry(_args())
        assert entry.sleep_quality is None
        assert entry.hooper_index is None


class TestMainEndToEnd:
    def test_logs_a_new_entry(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_wellness.main(
            [
                "--date",
                "2026-08-27",
                "--sleep-quality",
                "2",
                "--stress",
                "3",
                "--fatigue",
                "2",
                "--soreness",
                "4",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM subjective_log").fetchone()
        conn.close()

        assert row["hooper_index"] == 11
        assert "hooper_index=11" in capsys.readouterr().out

    def test_reupserting_same_date_updates_not_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "test.db"
        common = ["--date", "2026-08-27", "--db-path", str(db_path)]
        log_wellness.main(
            [*common, "--sleep-quality", "5", "--stress", "5", "--fatigue", "5", "--soreness", "5"]
        )
        capsys.readouterr()
        rc = log_wellness.main(
            [*common, "--sleep-quality", "2", "--stress", "2", "--fatigue", "2", "--soreness", "2"]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM subjective_log").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["hooper_index"] == 8
        assert "Updating existing entry" in capsys.readouterr().out

    def test_protein_and_social_meal_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        rc = log_wellness.main(
            ["--date", "2026-08-27", "--protein-hit", "--social-meal", "--db-path", str(db_path)]
        )
        assert rc == 0

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM subjective_log").fetchone()
        conn.close()

        assert row["protein_hit"] == 1
        assert row["social_meal"] == 1
        assert row["hooper_index"] is None
