from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import log_health_history  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    defaults = dict(
        kind=None,
        date=None,
        notes=None,
        db_path=None,
        test_name=None,
        value=None,
        unit=None,
        reference_range_low=None,
        reference_range_high=None,
        title=None,
        event_category=None,
        status=None,
        resolved_date=None,
        name=None,
        med_type=None,
        dosage=None,
        frequency=None,
        start_date=None,
        end_date=None,
        allergen=None,
        reaction=None,
        severity=None,
        date_identified=None,
        relation=None,
        condition=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestResolveEntriesFlagMode:
    def test_bloodwork_flag_mode(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(
                kind="bloodwork",
                date="2026-09-14",
                test_name="ferritin",
                value=85.0,
                unit="ng/mL",
                reference_range_low=30.0,
                reference_range_high=400.0,
            )
        )
        assert kind == "bloodwork"
        assert len(entries) == 1
        assert entries[0].test_name == "ferritin"
        assert entries[0].value == 85.0

    def test_bloodwork_missing_required_flag_raises(self) -> None:
        with pytest.raises(SystemExit, match="--value"):
            log_health_history.resolve_entries(_args(kind="bloodwork", test_name="ferritin"))

    def test_medical_event_flag_mode(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(
                kind="medical_event",
                date="2018-03-01",
                title="Right knee ACL tear",
                event_category="injury",
                status="ongoing",
            )
        )
        assert kind == "medical_event"
        assert entries[0].category == "injury"
        assert entries[0].status == "ongoing"

    def test_medical_event_resolved_round_trips_resolved_date(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(
                kind="medical_event",
                title="Wisdom teeth removal",
                event_category="surgery",
                status="resolved",
                resolved_date="2024-01-24",
            )
        )
        assert entries[0].resolved_date == "2024-01-24"

    def test_medication_flag_mode_defaults_start_date_to_today(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(kind="medication", name="Vitamin D3", med_type="supplement", dosage="2000 IU")
        )
        assert kind == "medication"
        assert entries[0].start_date == log_health_history._today_madrid()
        assert entries[0].end_date is None

    def test_medication_missing_required_flags_lists_both(self) -> None:
        with pytest.raises(SystemExit, match="--name, --med-type"):
            log_health_history.resolve_entries(_args(kind="medication"))

    def test_allergy_flag_mode(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(kind="allergy", allergen="peanuts", severity="moderate", reaction="hives")
        )
        assert kind == "allergy"
        assert entries[0].allergen == "peanuts"
        assert entries[0].severity == "moderate"

    def test_family_history_flag_mode(self) -> None:
        kind, entries = log_health_history.resolve_entries(
            _args(kind="family_history", relation="mother", condition="hypertension")
        )
        assert kind == "family_history"
        assert entries[0].relation == "mother"
        assert entries[0].condition == "hypertension"

    def test_invalid_dataclass_value_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="category"):
            log_health_history.resolve_entries(
                _args(kind="medical_event", title="x", event_category="bogus", status="ongoing")
            )


class TestResolveEntriesInteractiveMode:
    def test_no_kind_triggers_interactive_prompt_for_kind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = iter(
            [
                "family_history",  # kind
                "mother",  # relation
                "hypertension",  # condition
                "",  # notes
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        kind, entries = log_health_history.resolve_entries(_args())
        assert kind == "family_history"
        assert entries[0].relation == "mother"
        assert entries[0].condition == "hypertension"

    def test_bloodwork_interactive_loops_over_multiple_tests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = iter(
            [
                "bloodwork",  # kind
                "2026-09-14",  # draw date
                "ferritin",  # test 1 name
                "85",  # value
                "ng/mL",  # unit
                "30",  # range low
                "400",  # range high
                "",  # notes
                "total_testosterone",  # test 2 name
                "18.5",  # value
                "nmol/L",  # unit
                "",  # range low (skip)
                "",  # range high (skip)
                "",  # notes
                "",  # blank test name -> ends panel
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        kind, entries = log_health_history.resolve_entries(_args())
        assert kind == "bloodwork"
        assert len(entries) == 2
        assert entries[0].test_name == "ferritin"
        assert entries[0].reference_range_low == 30.0
        assert entries[1].test_name == "total_testosterone"
        assert entries[1].reference_range_low is None

    def test_bloodwork_interactive_zero_tests_is_valid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = iter(["bloodwork", "2026-09-14", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        kind, entries = log_health_history.resolve_entries(_args())
        assert kind == "bloodwork"
        assert entries == []

    def test_medical_event_interactive_only_prompts_resolved_date_when_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        answers = iter(
            [
                "medical_event",  # kind
                "2024-01-10",  # date
                "surgery",  # category
                "Wisdom teeth removal",  # title
                "resolved",  # status
                "2024-01-24",  # resolved date (only asked because resolved)
                "",  # notes
            ]
        )
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        kind, entries = log_health_history.resolve_entries(_args())
        assert entries[0].resolved_date == "2024-01-24"

    def test_allergy_interactive_severity_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        answers = iter(["allergy", "peanuts", "hives", "", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        kind, entries = log_health_history.resolve_entries(_args())
        assert entries[0].severity is None


class TestMainEndToEnd:
    def test_logs_bloodwork(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        rc = log_health_history.main(
            [
                "--kind",
                "bloodwork",
                "--test-name",
                "ferritin",
                "--value",
                "85",
                "--unit",
                "ng/mL",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bloodwork_results").fetchone()
        conn.close()
        assert row["test_name"] == "ferritin"
        assert row["value"] == 85.0
        assert "Logged:" in capsys.readouterr().out

    def test_bloodwork_repeated_inserts_never_overwrite(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = ["--kind", "bloodwork", "--test-name", "ferritin", "--db-path", str(db_path)]
        log_health_history.main([*common, "--value", "85"])
        log_health_history.main([*common, "--value", "90"])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM bloodwork_results").fetchall()
        conn.close()
        assert len(rows) == 2

    def test_logs_medical_event(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        rc = log_health_history.main(
            [
                "--kind",
                "medical_event",
                "--date",
                "2018-03-01",
                "--title",
                "Right knee ACL tear",
                "--event-category",
                "injury",
                "--status",
                "ongoing",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM medical_events").fetchone()
        conn.close()
        assert row["category"] == "injury"
        assert row["status"] == "ongoing"

    def test_logs_medication(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        rc = log_health_history.main(
            [
                "--kind",
                "medication",
                "--name",
                "Vitamin D3",
                "--med-type",
                "supplement",
                "--dosage",
                "2000 IU",
                "--frequency",
                "daily",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM medications_supplements").fetchone()
        conn.close()
        assert row["name"] == "Vitamin D3"
        assert row["end_date"] is None

    def test_allergy_upsert_updates_not_duplicates(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "test.db"
        common = ["--kind", "allergy", "--allergen", "peanuts", "--db-path", str(db_path)]
        log_health_history.main([*common, "--severity", "mild"])
        capsys.readouterr()
        rc = log_health_history.main([*common, "--severity", "severe"])
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM allergies").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["severity"] == "severe"
        assert "Updating existing allergy entry" in capsys.readouterr().out

    def test_family_history_upsert_updates_not_duplicates(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        common = [
            "--kind",
            "family_history",
            "--relation",
            "mother",
            "--condition",
            "asthma",
            "--db-path",
            str(db_path),
        ]
        log_health_history.main([*common, "--notes", "mild"])
        rc = log_health_history.main([*common, "--notes", "severe"])
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM family_medical_history").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["notes"] == "severe"

    def test_invalid_value_via_cli_returns_error(self, tmp_path: Path) -> None:
        # argparse's own `choices=` already rejects an invalid enum value
        # (exit code 2, before main()'s own error handling ever runs) --
        # this exercises a dataclass-level cross-field validation instead
        # (an inverted bloodwork reference range), which argparse can't catch.
        db_path = tmp_path / "test.db"
        rc = log_health_history.main(
            [
                "--kind",
                "bloodwork",
                "--test-name",
                "ferritin",
                "--value",
                "85",
                "--range-low",
                "400",
                "--range-high",
                "30",
                "--db-path",
                str(db_path),
            ]
        )
        assert rc == 1

    def test_interactive_bloodwork_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "test.db"
        answers = iter(["bloodwork", "2026-09-14", "ferritin", "85", "ng/mL", "", "", "", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        rc = log_health_history.main(["--db-path", str(db_path)])
        assert rc == 0
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM bloodwork_results").fetchone()
        conn.close()
        assert row["test_name"] == "ferritin"
