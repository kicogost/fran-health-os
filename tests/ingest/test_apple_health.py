from __future__ import annotations

from pathlib import Path

import pytest

from health_os.ingest.apple_health import (
    AppleHealthSourceConfig,
    is_excluded_source,
    parse_daily_weight,
    parse_workouts,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "apple_health_export"

TEST_CONFIG = AppleHealthSourceConfig(
    exclude_source_names=frozenset({"Connect", "Strava"}),
    exclude_source_name_substrings=("roberta",),
    weight_source_names=frozenset({"Renpho", "RENPHO Health"}),
)


class TestAppleHealthSourceConfigFromYaml:
    def test_loads_real_project_config(self) -> None:
        config = AppleHealthSourceConfig.from_yaml()
        assert "Connect" in config.exclude_source_names
        assert "Strava" in config.exclude_source_names
        assert "roberta" in config.exclude_source_name_substrings
        assert "Renpho" in config.weight_source_names


class TestIsExcludedSource:
    def test_exact_name_match(self) -> None:
        assert is_excluded_source("Connect", TEST_CONFIG) is True
        assert is_excluded_source("Strava", TEST_CONFIG) is True

    def test_substring_match_case_insensitive(self) -> None:
        assert is_excluded_source("Apple Watch de roberta", TEST_CONFIG) is True
        assert is_excluded_source("APPLE WATCH DE ROBERTA", TEST_CONFIG) is True

    def test_not_excluded(self) -> None:
        assert is_excluded_source("BJJBuddy", TEST_CONFIG) is False
        assert is_excluded_source("Francisco’s Apple\xa0Watch", TEST_CONFIG) is False


class TestParseWorkouts:
    def test_excludes_known_duplicate_and_foreign_sources(self) -> None:
        activities = list(parse_workouts(FIXTURE_DIR))
        sources = {a.source for a in activities}
        assert sources == {"apple_health"}
        # Fixture has 5 Workouts: BJJBuddy, Watch-Running, Connect, Strava, roberta.
        # Only the first two should survive.
        assert len(activities) == 2

    def test_bjjbuddy_workout_fields(self) -> None:
        activities = list(parse_workouts(FIXTURE_DIR))
        bjj = next(a for a in activities if a.sport == "martial_arts")
        assert bjj.source == "apple_health"
        assert bjj.duration_s == 3600
        assert bjj.start_utc == "2026-08-10T06:06:44Z"
        assert bjj.local_date == "2026-08-10"
        assert bjj.distance_m is None
        assert bjj.avg_hr is None  # no reliable inline HR on real Workout elements

    def test_running_workout_distance_converted_from_km(self) -> None:
        activities = list(parse_workouts(FIXTURE_DIR))
        run = next(a for a in activities if a.sport == "running")
        assert run.distance_m == pytest.approx(5020.0)

    def test_ids_are_stable_across_reparse(self) -> None:
        first = {a.activity_id for a in parse_workouts(FIXTURE_DIR)}
        second = {a.activity_id for a in parse_workouts(FIXTURE_DIR)}
        assert first == second


class TestParseDailyWeight:
    def test_only_known_scale_sources_included(self) -> None:
        metrics = {m.date: m for m in parse_daily_weight(FIXTURE_DIR)}
        # Fixture has weight records for 2026-08-13 (x2, Renpho), 2026-08-14
        # (RENPHO Health), and 2026-08-15 (HotSpot-named source, lb, must be excluded).
        assert set(metrics) == {"2026-08-13", "2026-08-14"}

    def test_latest_reading_wins_not_average(self) -> None:
        metrics = {m.date: m for m in parse_daily_weight(FIXTURE_DIR)}
        # Two Renpho readings on 2026-08-13: 78.05 then 78.20, 16s apart.
        # Latest (78.20) must win -- never averaged.
        assert metrics["2026-08-13"].weight_kg == 78.20

    def test_source_recorded_for_traceability(self) -> None:
        metrics = {m.date: m for m in parse_daily_weight(FIXTURE_DIR)}
        assert metrics["2026-08-13"].sources == {"weight_kg": "apple_health:renpho"}
        assert metrics["2026-08-14"].sources == {"weight_kg": "apple_health:renpho health"}
