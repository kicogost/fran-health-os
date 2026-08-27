from __future__ import annotations

from pathlib import Path

import pytest

from health_os.ingest.strava_bulk import parse_activities_csv

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "strava_export"


class TestParseActivitiesCsv:
    def test_yields_one_activity_per_valid_row(self) -> None:
        activities = list(parse_activities_csv(FIXTURE_DIR))
        # 3 rows in the fixture, one has a blank Activity ID and must be skipped.
        assert len(activities) == 2

    def test_ride_fields(self) -> None:
        activities = {a.source_id: a for a in parse_activities_csv(FIXTURE_DIR)}
        ride = activities["1111111111"]
        assert ride.source == "strava"
        assert ride.activity_id == "strava:1111111111"
        assert ride.sport == "ride"
        assert ride.duration_s == 3600
        assert ride.distance_m == 30000.0
        assert ride.avg_hr == 130
        assert ride.max_hr == 175
        assert ride.avg_power == 150.0
        assert ride.elevation_gain_m == 400.0
        assert ride.training_load == 80.0

    def test_activity_date_is_madrid_local_converted_to_utc(self) -> None:
        # "Aug 22, 2026, 6:52:17 AM" local (CEST, UTC+2) -> 04:52:17 UTC.
        activities = {a.source_id: a for a in parse_activities_csv(FIXTURE_DIR)}
        ride = activities["1111111111"]
        assert ride.start_utc == "2026-08-22T04:52:17Z"
        assert ride.local_date == "2026-08-22"

    def test_weight_training_row_no_distance(self) -> None:
        activities = {a.source_id: a for a in parse_activities_csv(FIXTURE_DIR)}
        weights = activities["2222222222"]
        assert weights.sport == "weight_training"
        assert weights.distance_m == 0.0
        assert weights.perceived_rpe == 6

    def test_blank_activity_id_skipped(self) -> None:
        activities = list(parse_activities_csv(FIXTURE_DIR))
        assert all(a.source_id for a in activities)

    def test_rejects_wrong_header_shape(self, tmp_path: Path) -> None:
        bad_csv = tmp_path / "activities.csv"
        bad_csv.write_text("Activity ID,Activity Date\n123,Aug 1, 2026, 1:00:00 AM\n")
        with pytest.raises(ValueError, match="columns, expected"):
            list(parse_activities_csv(tmp_path))
