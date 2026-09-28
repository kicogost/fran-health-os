from __future__ import annotations

import json
from pathlib import Path

import pytest

from health_os.ingest.health_auto_export import _read_json_with_retry, parse_body_composition

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "health_auto_export"


class TestParseBodyComposition:
    def test_latest_reading_per_date_wins(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        # 2026-01-28 has two RENPHO weight readings (07:00 -> 80.0, 19:00 ->
        # 80.5) -- the later one should win, never averaged.
        assert by_date["2026-01-28"].weight_kg == pytest.approx(80.5)

    def test_lean_body_mass_extracted_into_its_own_field(self) -> None:
        # Real gap closed 2026-08-29 (Francisco asked whether Apple Health
        # surfaces Renpho's body-composition data): lean_body_mass used to
        # be read and explicitly discarded so it could never leak into
        # weight_kg; it's now extracted into its own field instead.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-01-28"].lean_body_mass_kg == pytest.approx(60.0)
        assert by_date["2026-01-28"].weight_kg == pytest.approx(80.5)  # still unaffected

    def test_bmi_extracted_with_no_unit_conversion(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-01-28"].bmi == pytest.approx(25.8)

    def test_unrelated_metrics_ignored(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        # heart_rate shares a file with the body-composition metrics but
        # must never surface as any DailyMetric field.
        for metric in by_date.values():
            assert metric.resting_hr is None
            assert metric.hrv_overnight_ms is None

    def test_a_date_with_only_weight_leaves_other_fields_none(self) -> None:
        # 2026-01-29 has a weight reading but no lean mass/BMI that day --
        # fields must be independently optional, never invented to match
        # whatever the previous or next date happened to have.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-01-29"].weight_kg == pytest.approx(79.0)
        assert by_date["2026-01-29"].lean_body_mass_kg is None
        assert by_date["2026-01-29"].bmi is None

    def test_unknown_source_filtered_before_latest_wins_comparison(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        # 2026-01-29: a real RENPHO reading (79.0) at 08:00, and a bogus
        # 999.0 from an unlisted source ("SomeRandomApp") at 09:00 -- later
        # timestamp must NOT win just because it's later; it should never
        # have entered the candidate pool at all.
        assert by_date["2026-01-29"].weight_kg == pytest.approx(79.0)

    def test_combines_multiple_files_in_directory(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        # 2026-01-28 comes from one fixture file, 2026-01-29 from another,
        # 2026-01-30 from a third -- all three dates must show up together.
        assert set(by_date) == {"2026-01-28", "2026-01-29", "2026-01-30"}

    def test_pound_unit_converted_to_kg(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-01-30"].weight_kg == pytest.approx(80.0, abs=0.01)

    def test_sources_tagged_with_lowercased_source_name_per_field(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-01-28"].sources == {
            "weight_kg": "apple_health:renpho health",
            "lean_body_mass_kg": "apple_health:renpho health",
            "bmi": "apple_health:renpho health",
        }

    def test_empty_directory_yields_nothing(self, tmp_path: Path) -> None:
        assert list(parse_body_composition(tmp_path)) == []

    def test_non_matching_files_in_directory_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "not_a_health_export.json").write_text("{}")
        assert list(parse_body_composition(tmp_path)) == []

    def test_one_malformed_entry_does_not_discard_other_valid_readings(
        self, tmp_path: Path
    ) -> None:
        # Real bug found 2026-08-28: parse_body_composition() (then
        # parse_weight()) built its whole result dict in one pass with no
        # per-record isolation, so a single bad record ANYWHERE (an
        # unrecognized unit, an unparseable date) raised uncaught before a
        # single DailyMetric was ever yielded -- discarding every good
        # reading in every file, not just the bad one.
        (tmp_path / "HealthAutoExport-good.json").write_text(
            json.dumps(
                {
                    "data": {
                        "metrics": [
                            {
                                "name": "weight_body_mass",
                                "units": "kg",
                                "data": [
                                    {
                                        "qty": 78.45,
                                        "date": "2026-08-21 00:00:00 +0200",
                                        "source": "RENPHO Health",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )
        (tmp_path / "HealthAutoExport-bad.json").write_text(
            json.dumps(
                {
                    "data": {
                        "metrics": [
                            {
                                "name": "weight_body_mass",
                                "units": "st",  # unrecognized unit -- real trigger
                                "data": [
                                    {
                                        "qty": 12.0,
                                        "date": "2026-08-22 00:00:00 +0200",
                                        "source": "RENPHO Health",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )

        errors: list[str] = []
        by_date = {m.date: m for m in parse_body_composition(tmp_path, errors=errors)}

        assert by_date["2026-08-21"].weight_kg == pytest.approx(78.45)
        assert "2026-08-22" not in by_date
        assert len(errors) == 1
        assert "st" in errors[0]

    def test_body_fat_percentage_extracted_into_its_own_field(self, tmp_path: Path) -> None:
        # Real correction, 2026-09-28: checked against Francisco's real
        # export on 2026-08-29 and body_fat_percentage was confirmed absent
        # from HealthKit on his account -- re-checked a fresh export on
        # 2026-09-28 and it's now present (Renpho evidently started writing
        # it at some point in between, a phone-side change, not anything in
        # this codebase). Now a real, extracted column, same as weight/lean
        # mass/BMI.
        (tmp_path / "HealthAutoExport-hypothetical.json").write_text(
            json.dumps(
                {
                    "data": {
                        "metrics": [
                            {
                                "name": "body_fat_percentage",
                                "units": "%",
                                "data": [
                                    {
                                        "qty": 24.5,
                                        "date": "2026-09-27 00:00:00 +0200",
                                        "source": "RENPHO Health",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
        )
        by_date = {m.date: m for m in parse_body_composition(tmp_path)}
        assert by_date["2026-09-27"].body_fat_pct == pytest.approx(24.5)
        # No unit conversion applied -- "%" is already the right scale.
        assert by_date["2026-09-27"].weight_kg is None


class TestReadJsonWithRetry:
    """Real, reproduced failure mode (2026-09-28): a freshly-synced file
    under an on-demand iCloud Drive folder can transiently raise
    `OSError: [Errno 11] Resource deadlock avoided` while macOS's iCloud
    FileProvider daemon is still materializing it -- confirmed by watching a
    real sync fail identically 4 times over ~18 hours, then succeed once the
    file was read manually with nothing else changed. `_read_json_with_retry`
    retries specifically on `OSError`, never on a real data problem
    (`json.JSONDecodeError`, a `ValueError` subtype).
    """

    def test_retries_transient_oserror_and_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "f.json"
        path.write_text(json.dumps({"data": {"metrics": []}}))
        real_open = Path.open
        calls = {"n": 0}

        def flaky_open(self: Path, *args: object, **kwargs: object):
            calls["n"] += 1
            if calls["n"] < 3:
                raise OSError(11, "Resource deadlock avoided")
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", flaky_open)
        monkeypatch.setattr("health_os.ingest.health_auto_export.time.sleep", lambda _seconds: None)

        result = _read_json_with_retry(path)
        assert result == {"data": {"metrics": []}}
        assert calls["n"] == 3

    def test_reraises_the_real_error_after_exhausting_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "f.json"
        path.write_text("{}")

        def always_fails(self: Path, *args: object, **kwargs: object):
            raise OSError(11, "Resource deadlock avoided")

        monkeypatch.setattr(Path, "open", always_fails)
        monkeypatch.setattr("health_os.ingest.health_auto_export.time.sleep", lambda _seconds: None)

        with pytest.raises(OSError, match="Resource deadlock avoided"):
            _read_json_with_retry(path)

    def test_a_real_bad_file_is_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Malformed JSON is a real data problem, not a transient race --
        # retrying it would just waste time before failing the same way.
        path = tmp_path / "bad.json"
        path.write_text("not json")
        real_open = Path.open
        calls = {"n": 0}

        def counting_open(self: Path, *args: object, **kwargs: object):
            calls["n"] += 1
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", counting_open)
        with pytest.raises(json.JSONDecodeError):
            _read_json_with_retry(path)
        assert calls["n"] == 1
