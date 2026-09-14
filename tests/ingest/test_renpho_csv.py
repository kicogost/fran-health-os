from __future__ import annotations

from pathlib import Path

import pytest

from health_os.ingest.renpho_csv import parse_body_composition

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "renpho_csv"


class TestParseBodyComposition:
    def test_latest_row_wins_across_multiple_same_day_readings(self) -> None:
        # 2026-06-01 has two rows: 06:00 (75.00kg) and 20:00 (78.00kg). The
        # later row must win AS A WHOLE UNIT -- every field below comes from
        # the 20:00 row, never mixed with the 06:00 row's values, since both
        # rows represent one coherent weigh-in event each.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        m = by_date["2026-06-01"]
        assert m.weight_kg == pytest.approx(78.00)
        assert m.bmi == pytest.approx(25.0)
        assert m.body_fat_pct == pytest.approx(23.0)
        assert m.skeletal_muscle_pct == pytest.approx(47.0)
        assert m.lean_body_mass_kg == pytest.approx(60.00)
        assert m.subcutaneous_fat_pct == pytest.approx(20.0)
        assert m.visceral_fat_rating == 7
        assert m.body_water_pct == pytest.approx(53.5)
        assert m.muscle_mass_kg == pytest.approx(55.00)
        assert m.bone_mass_kg == pytest.approx(2.98)
        assert m.protein_pct == pytest.approx(17.3)
        assert m.bmr_kcal == 1640
        assert m.metabolic_age == 23

    def test_dash_fields_parsed_as_none_never_invented(self) -> None:
        # 2026-06-02 has a real weight/BMI reading but every other
        # body-composition field is "--" (a failed bioimpedance measurement)
        # -- must be None, never 0 or copied from another date/row.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        m = by_date["2026-06-02"]
        assert m.weight_kg == pytest.approx(74.50)
        assert m.bmi == pytest.approx(23.0)
        assert m.body_fat_pct is None
        assert m.skeletal_muscle_pct is None
        assert m.lean_body_mass_kg is None
        assert m.subcutaneous_fat_pct is None
        assert m.visceral_fat_rating is None
        assert m.body_water_pct is None
        assert m.muscle_mass_kg is None
        assert m.bone_mass_kg is None
        assert m.protein_pct is None
        assert m.bmr_kcal is None
        assert m.metabolic_age is None

    def test_date_parsed_day_first_not_month_first(self) -> None:
        # "25/12/2026" is unambiguous as DD/MM/YYYY -- there is no 13th
        # month, so this row's very presence (parsed with no error) at
        # local_date "2026-12-25" is real proof of day-first parsing, not an
        # assumption: parsing it as MM/DD would raise ValueError on "month 25"
        # and the row would end up skipped into `errors` instead.
        errors: list[str] = []
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR, errors=errors)}
        assert "2026-12-25" in by_date
        assert by_date["2026-12-25"].weight_kg == pytest.approx(70.00)
        assert not any("25/12/2026" in e for e in errors)

    def test_protein_header_with_internal_parenthesis_space_parsed(self) -> None:
        # "Protein (%)" has a genuine internal space before its parenthesis
        # (distinct from the comma-adjacent header spacing elsewhere) --
        # confirms the lookup key isn't mangled by skipinitialspace handling.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert by_date["2026-12-25"].protein_pct == pytest.approx(17.0)

    def test_local_time_near_midnight_does_not_shift_calendar_date_winter(self) -> None:
        # 15/01/2026 23:30 local (Europe/Madrid, CET = UTC+1 in January) --
        # converting through localize_to_utc() and back via to_local_date()
        # must land back on the SAME local calendar date, not the next day.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert "2026-01-15" in by_date
        assert by_date["2026-01-15"].weight_kg == pytest.approx(79.00)

    def test_local_time_near_midnight_does_not_shift_calendar_date_summer(self) -> None:
        # Same check under Europe/Madrid's summer DST offset (CEST = UTC+2)
        # -- both offsets must round-trip the calendar date correctly.
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        assert "2026-07-15" in by_date
        assert by_date["2026-07-15"].weight_kg == pytest.approx(79.50)

    def test_malformed_row_does_not_discard_other_valid_rows(self) -> None:
        # "99/13/2026" (day 99, month 13) is unparseable under any date
        # convention -- must be skipped and recorded in `errors`, without
        # discarding any other valid row in the same file.
        errors: list[str] = []
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR, errors=errors)}
        assert "2026-06-01" in by_date  # a valid row from the same file
        assert "2026-12-25" in by_date  # another valid row from the same file
        assert len(errors) == 1
        assert "export_a.csv" in errors[0]

    def test_combines_multiple_files_in_directory(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        # 2026-03-10 only exists in export_b.csv -- must show up alongside
        # export_a.csv's dates.
        assert "2026-03-10" in by_date
        assert by_date["2026-03-10"].weight_kg == pytest.approx(76.00)

    def test_sources_tagged_as_renpho_csv_for_every_present_field(self) -> None:
        by_date = {m.date: m for m in parse_body_composition(FIXTURE_DIR)}
        m = by_date["2026-06-02"]  # weight_kg + bmi only, rest "--"
        assert m.sources == {"weight_kg": "renpho_csv", "bmi": "renpho_csv"}

    def test_empty_directory_yields_nothing(self, tmp_path: Path) -> None:
        assert list(parse_body_composition(tmp_path)) == []

    def test_non_csv_files_in_directory_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not a csv file")
        assert list(parse_body_composition(tmp_path)) == []

    def test_row_missing_date_or_time_is_skipped_silently(self, tmp_path: Path) -> None:
        (tmp_path / "export.csv").write_text(
            "Date, Time, Weight(kg),BMI\n"
            ",08:00:00,70.00,22.0\n"  # missing Date
            "01/01/2026,,70.00,22.0\n"  # missing Time
            "02/01/2026,08:00:00,71.00,22.5\n"  # valid
        )
        errors: list[str] = []
        by_date = {m.date: m for m in parse_body_composition(tmp_path, errors=errors)}
        assert set(by_date) == {"2026-01-02"}
        assert errors == []  # a blank date/time is a skip, not a parse error
