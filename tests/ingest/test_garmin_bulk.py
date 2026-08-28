from __future__ import annotations

from pathlib import Path

import pytest

from health_os.ingest.garmin_bulk import parse_activities, parse_daily_metrics

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "garmin_bulk_export"


class TestParseActivities:
    def test_skips_entries_missing_activity_id(self) -> None:
        activities = list(parse_activities(FIXTURE_DIR))
        assert len(activities) == 2

    def test_ride_unit_conversions_and_zone_folding(self) -> None:
        activities = {a.source_id: a for a in parse_activities(FIXTURE_DIR)}
        ride = activities["90000000001"]
        assert ride.activity_id == "garmin:90000000001"
        assert ride.source == "garmin"
        assert ride.sport == "cycling"
        # 2026-01-15T23:30:00Z -> CET (UTC+1) in January -> 2026-01-16 00:30 local.
        assert ride.start_utc == "2026-01-15T23:30:00Z"
        assert ride.local_date == "2026-01-16"
        assert ride.duration_s == 3600  # 3,600,000 ms
        assert ride.distance_m == pytest.approx(20000.0)  # 2,000,000 cm
        assert ride.elevation_gain_m == pytest.approx(300.0)  # 30,000 cm
        assert ride.avg_hr == 140
        assert ride.max_hr == 165
        assert ride.aerobic_te == pytest.approx(3.2)
        assert ride.anaerobic_te == pytest.approx(1.1)
        assert ride.avg_power == pytest.approx(180.0)
        # Zone folding: zone1 = zone0+zone1, zone5 = zone5+zone6, in seconds.
        assert ride.hr_zone_1_s == 660
        assert ride.hr_zone_2_s == 1200
        assert ride.hr_zone_3_s == 900
        assert ride.hr_zone_4_s == 600
        assert ride.hr_zone_5_s == 240

    def test_run_missing_optional_fields_stay_none(self) -> None:
        activities = {a.source_id: a for a in parse_activities(FIXTURE_DIR)}
        run = activities["90000000002"]
        assert run.sport == "running"
        assert run.distance_m == pytest.approx(5000.0)
        assert run.avg_power is None
        assert run.elevation_gain_m is None
        assert run.hr_zone_1_s is None
        # 2026-01-15T10:00:00Z -> CET (+1) -> 11:00 local, no date rollover.
        assert run.local_date == "2026-01-15"


class TestParseDailyMetrics:
    def test_full_day_all_three_sources_merged(self) -> None:
        by_date = {m.date: m for m in parse_daily_metrics(FIXTURE_DIR)}
        day = by_date["2026-01-15"]

        # UDS
        assert day.steps == 8500
        assert day.active_kcal == 450
        assert day.total_kcal == 2400
        assert day.resting_hr == 50  # prefers restingHeartRate over currentDayRestingHeartRate
        assert day.body_battery_max == 85
        assert day.body_battery_min == 20
        assert day.stress_avg == 28  # TOTAL aggregator only, not AWAKE's 35
        assert day.respiration_avg == pytest.approx(14.5)

        # Sleep
        assert day.sleep_deep_min == 60
        assert day.sleep_light_min == 240
        assert day.sleep_rem_min == 90
        assert day.sleep_awake_min == 10
        assert day.sleep_total_min == 390  # deep+light+rem, excludes awake
        assert day.sleep_score == 82

        # Health status (LHA)
        assert day.hrv_overnight_ms == pytest.approx(95.0)
        assert day.hrv_status == "IN_RANGE"
        assert day.spo2_avg == pytest.approx(97.0)
        assert day.skin_temp_delta == pytest.approx(-0.2)

    def test_every_populated_field_tagged_garmin(self) -> None:
        by_date = {m.date: m for m in parse_daily_metrics(FIXTURE_DIR)}
        day = by_date["2026-01-15"]
        assert day.sources["hrv_overnight_ms"] == "garmin"
        assert day.sources["steps"] == "garmin"
        assert day.sources["sleep_score"] == "garmin"
        assert "weight_kg" not in day.sources  # never populated, never tagged

    def test_partial_day_missing_subobjects_handled_gracefully(self) -> None:
        by_date = {m.date: m for m in parse_daily_metrics(FIXTURE_DIR)}
        day = by_date["2026-01-16"]

        assert day.steps == 3000
        assert day.resting_hr is None  # neither field present in the fixture day
        assert day.body_battery_max is None  # no bodyBattery object at all
        assert day.stress_avg is None  # no allDayStress object at all

        assert day.sleep_deep_min == 50
        assert day.sleep_light_min == 200
        assert day.sleep_rem_min is None  # missing from fixture
        assert day.sleep_total_min is None  # never computed from a partial trio
        assert day.sleep_score is None  # no sleepScores object

        assert day.hrv_overnight_ms == pytest.approx(70.0)
        assert day.hrv_status == "LOW"
        assert day.spo2_avg is None  # SPO2 entry present but has no "value"

    def test_dates_yielded_in_ascending_order(self) -> None:
        dates = [m.date for m in parse_daily_metrics(FIXTURE_DIR)]
        assert dates == sorted(dates)
