from __future__ import annotations

import json
from pathlib import Path

import pytest

from health_os.ingest.health_auto_export import parse_weight

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "health_auto_export"


class TestParseWeight:
    def test_latest_reading_per_date_wins(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        # 2026-01-28 has two RENPHO readings (07:00 -> 80.0, 19:00 -> 80.5) --
        # the later one should win, never averaged.
        assert by_date["2026-01-28"].weight_kg == pytest.approx(80.5)

    def test_unrelated_metrics_ignored(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        # lean_body_mass/heart_rate share a file with weight_body_mass but
        # must never leak into weight_kg or otherwise surface.
        for metric in by_date.values():
            assert metric.weight_kg is not None

    def test_unknown_source_filtered_before_latest_wins_comparison(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        # 2026-01-29: a real RENPHO reading (79.0) at 08:00, and a bogus
        # 999.0 from an unlisted source ("SomeRandomApp") at 09:00 -- later
        # timestamp must NOT win just because it's later; it should never
        # have entered the candidate pool at all.
        assert by_date["2026-01-29"].weight_kg == pytest.approx(79.0)

    def test_combines_multiple_files_in_directory(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        # 2026-01-28 comes from one fixture file, 2026-01-29 from another,
        # 2026-01-30 from a third -- all three dates must show up together.
        assert set(by_date) == {"2026-01-28", "2026-01-29", "2026-01-30"}

    def test_pound_unit_converted_to_kg(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        assert by_date["2026-01-30"].weight_kg == pytest.approx(80.0, abs=0.01)

    def test_sources_tagged_with_lowercased_source_name(self) -> None:
        by_date = {m.date: m for m in parse_weight(FIXTURE_DIR)}
        assert by_date["2026-01-28"].sources == {"weight_kg": "apple_health:renpho health"}

    def test_empty_directory_yields_nothing(self, tmp_path: Path) -> None:
        assert list(parse_weight(tmp_path)) == []

    def test_non_matching_files_in_directory_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "not_a_health_export.json").write_text("{}")
        assert list(parse_weight(tmp_path)) == []

    def test_one_malformed_entry_does_not_discard_other_valid_readings(
        self, tmp_path: Path
    ) -> None:
        # Real bug found 2026-08-28: parse_weight() built its whole result
        # dict in one pass with no per-record isolation, so a single bad
        # record ANYWHERE (an unrecognized unit, an unparseable date) raised
        # uncaught before a single DailyMetric was ever yielded -- discarding
        # every good reading in every file, not just the bad one.
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
        by_date = {m.date: m for m in parse_weight(tmp_path, errors=errors)}

        assert by_date["2026-08-21"].weight_kg == pytest.approx(78.45)
        assert "2026-08-22" not in by_date
        assert len(errors) == 1
        assert "st" in errors[0]
