from __future__ import annotations

import json
import sqlite3

from health_os.api.trends import (
    READINESS_MIN_DAYS_FOR_WEAK_COMPONENT,
    _body_fat_pct_window_meaning,
    _fat_mass_window_meaning,
    _hrv_window_meaning,
    _readiness_weakest_component,
    _rhr_window_meaning,
    _sleep_total_window_meaning,
    _weight_window_meaning,
    build_trends_payload,
)
from health_os.core import db as db_module
from health_os.core.models import DailyMetric

_CONFIG = {"goals": {"primary": {"date": "2026-10-18", "weight_division_kg": 77.0}}}


def _write_derived(
    conn: sqlite3.Connection,
    date: str,
    value: float | None,
    confidence: str,
    components: dict | None = None,
) -> None:
    row = {"date": date, "metric_name": "readiness_score", "value": value, "confidence": confidence}
    if components is not None:
        row["inputs_json"] = json.dumps({"components": components})
    db_module.upsert(
        conn, "derived_daily", row, ["date", "metric_name"], touch_column="computed_at"
    )


class TestBuildTrendsPayload:
    def test_empty_db_returns_empty_series(self, conn: sqlite3.Connection) -> None:
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload == {
            "window_days": 90,
            "series": {},
            "sleep_stages": [],
            "sleep_total": {
                "label": "Total sleep",
                "raw": [],
                "average": {"value": None, "n_days": 0},
                "meaning": {"tone": "unknown", "headline": "No sleep data in this window yet."},
            },
            "readiness": {
                "label": "Readiness score",
                "raw": [],
                "smoothed": [],
                "coverage_summary": {},
                "average": {"value": None, "n_days": 0},
                "meaning": {
                    "tone": "unknown",
                    "headline": "Not enough readiness history in this window yet.",
                },
            },
            "insights": [],
        }

    def test_window_filters_out_older_rows(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-01-01", weight_kg=80.0).to_row(), ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-20", weight_kg=79.0).to_row(), ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 30, _CONFIG)
        dates = [p["date"] for p in payload["series"]["weight_kg"]["raw"]]
        assert dates == ["2026-08-20", "2026-08-28"]

    def test_smoothed_series_present_alongside_raw(self, conn: sqlite3.Connection) -> None:
        for d, w in [("2026-08-26", 80.0), ("2026-08-27", 79.5), ("2026-08-28", 79.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, weight_kg=w).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw = payload["series"]["weight_kg"]["raw"]
        smoothed = payload["series"]["weight_kg"]["smoothed"]
        assert len(raw) == len(smoothed) == 3
        # First smoothed point always equals the first raw point (EWMA seed).
        assert smoothed[0]["value"] == raw[0]["value"]

    def test_sleep_stages_only_include_days_with_at_least_one_stage(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-28", sleep_deep_min=60).to_row(),
            ["date"],
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-27", resting_hr=50).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert len(payload["sleep_stages"]) == 1
        assert payload["sleep_stages"][0]["date"] == "2026-08-28"
        assert payload["sleep_stages"][0]["sleep_deep_min"] == 60


class TestWindowAverageMatchesRaw:
    """Locks in the feature's own hard rule: the average shown next to a
    chart is ALWAYS `sum(raw)/len(raw)` of that same chart's own `raw`
    array -- never a separately-fetched or separately-windowed number. If a
    future change made these silently drift apart, these tests fail.
    """

    def test_weight_average_hand_verified(self, conn: sqlite3.Connection) -> None:
        for d, w in [("2026-08-26", 79.0), ("2026-08-27", 80.0), ("2026-08-28", 81.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, weight_kg=w).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw_values = [p["value"] for p in payload["series"]["weight_kg"]["raw"]]
        assert raw_values == [79.0, 80.0, 81.0]
        assert payload["series"]["weight_kg"]["average"] == {
            "value": sum(raw_values) / len(raw_values),
            "n_days": 3,
        }
        assert payload["series"]["weight_kg"]["average"]["value"] == 80.0

    def test_hrv_average_matches_raw(self, conn: sqlite3.Connection) -> None:
        for d, v in [("2026-08-26", 80.0), ("2026-08-27", 85.0), ("2026-08-28", 96.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, hrv_overnight_ms=v).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw_values = [p["value"] for p in payload["series"]["hrv_overnight_ms"]["raw"]]
        assert payload["series"]["hrv_overnight_ms"]["average"]["value"] == sum(raw_values) / len(
            raw_values
        )

    def test_resting_hr_average_matches_raw(self, conn: sqlite3.Connection) -> None:
        for d, v in [("2026-08-26", 48.0), ("2026-08-27", 51.0), ("2026-08-28", 55.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, resting_hr=v).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw_values = [p["value"] for p in payload["series"]["resting_hr"]["raw"]]
        assert payload["series"]["resting_hr"]["average"]["value"] == sum(raw_values) / len(
            raw_values
        )

    def test_readiness_average_matches_raw(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=80.0).to_row(), ["date"]
        )
        _write_derived(conn, "2026-08-26", 50.0, "full")
        _write_derived(conn, "2026-08-27", 60.0, "full")
        _write_derived(conn, "2026-08-28", 70.0, "full")
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw_values = [p["value"] for p in payload["readiness"]["raw"]]
        assert payload["readiness"]["average"]["value"] == sum(raw_values) / len(raw_values) == 60.0

    def test_sleep_total_average_matches_raw(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(
                date="2026-08-27", sleep_deep_min=60, sleep_light_min=200, sleep_rem_min=90
            ).to_row(),
            ["date"],
        )
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(
                date="2026-08-28", sleep_deep_min=70, sleep_light_min=210, sleep_rem_min=80
            ).to_row(),
            ["date"],
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["sleep_total"]["raw"] == [
            {"date": "2026-08-27", "value": 350},
            {"date": "2026-08-28", "value": 360},
        ]
        raw_values = [p["value"] for p in payload["sleep_total"]["raw"]]
        assert (
            payload["sleep_total"]["average"]["value"] == sum(raw_values) / len(raw_values) == 355.0
        )

    def test_sleep_total_excludes_days_with_a_partial_stage_breakdown(
        self, conn: sqlite3.Connection
    ) -> None:
        # deep present, light/rem missing -- design principle 6: never sum
        # a partial night as if it were the whole thing.
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-28", sleep_deep_min=60).to_row(),
            ["date"],
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["sleep_total"]["raw"] == []
        assert payload["sleep_total"]["average"] == {"value": None, "n_days": 0}

    def test_body_fat_pct_average_matches_raw(self, conn: sqlite3.Connection) -> None:
        for d, v in [("2026-08-26", 22.0), ("2026-08-27", 21.5), ("2026-08-28", 21.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, body_fat_pct=v).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw_values = [p["value"] for p in payload["series"]["body_fat_pct"]["raw"]]
        assert raw_values == [22.0, 21.5, 21.0]
        assert payload["series"]["body_fat_pct"]["average"] == {
            "value": sum(raw_values) / len(raw_values),
            "n_days": 3,
        }
        assert payload["series"]["body_fat_pct"]["average"]["value"] == 21.5

    def test_fat_mass_average_matches_raw_and_only_covers_paired_dates(
        self, conn: sqlite3.Connection
    ) -> None:
        # 2026-08-26 has both weight and body-fat% -- a real fat-mass point.
        # 2026-08-27 has weight only -- must NOT appear in fat_mass_kg at all
        # (design principle 6: never invent the missing half of the pair).
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-26", weight_kg=80.0, body_fat_pct=20.0).to_row(),
            ["date"],
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-27", weight_kg=79.0).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        raw = payload["series"]["fat_mass_kg"]["raw"]
        assert raw == [{"date": "2026-08-26", "value": 16.0}]
        raw_values = [p["value"] for p in raw]
        assert payload["series"]["fat_mass_kg"]["average"] == {
            "value": sum(raw_values) / len(raw_values),
            "n_days": 1,
        }
        assert payload["series"]["fat_mass_kg"]["average"]["value"] == 16.0

    def test_fat_mass_series_has_full_time_series_shape(self, conn: sqlite3.Connection) -> None:
        # Same shape as every other series in `payload["series"]" -- label,
        # raw, smoothed, average, meaning -- even though it's derived, not a
        # stored column.
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-28", weight_kg=80.0, body_fat_pct=20.0).to_row(),
            ["date"],
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        fat_mass = payload["series"]["fat_mass_kg"]
        assert set(fat_mass.keys()) == {"label", "raw", "smoothed", "average", "meaning"}
        assert fat_mass["smoothed"] == [{"date": "2026-08-28", "value": 16.0}]


class TestWeightWindowMeaning:
    """Direct unit tests of `_weight_window_meaning()` -- hand-computed,
    independent of any DB wiring, so the branch logic itself is pinned
    down precisely.
    """

    def test_no_data(self) -> None:
        result = _weight_window_meaning(None, {"confidence": "insufficient_data"}, 77.0, None)
        assert result == {"tone": "unknown", "headline": "No weight logged in this window yet."}

    def test_trend_unknown_over_limit_reads_bad(self) -> None:
        result = _weight_window_meaning(80.0, {"confidence": "insufficient_data"}, 77.0, None)
        assert result["tone"] == "bad"
        assert "3.0kg above your competition weight limit" in result["headline"]
        assert "not enough recent weigh-ins" in result["headline"]

    def test_trend_unknown_under_limit_reads_good(self) -> None:
        result = _weight_window_meaning(75.0, {"confidence": "insufficient_data"}, 77.0, None)
        assert result["tone"] == "good"
        assert "already at or under your competition weight limit" in result["headline"]

    def test_trend_unknown_no_goal_configured_reads_unknown(self) -> None:
        result = _weight_window_meaning(80.0, {"confidence": "insufficient_data"}, None, None)
        assert result["tone"] == "unknown"

    def test_flat_trend_over_limit_reads_bad(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.0,
            "ci_low_kg_per_week": -0.1,
            "ci_high_kg_per_week": 0.1,
        }
        result = _weight_window_meaning(80.0, trend, 77.0, None)
        assert result["tone"] == "bad"
        assert "holding steady" in result["headline"]

    def test_flat_trend_under_limit_reads_good(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.0,
            "ci_low_kg_per_week": -0.1,
            "ci_high_kg_per_week": 0.1,
        }
        result = _weight_window_meaning(75.0, trend, 77.0, None)
        assert result["tone"] == "good"

    def test_flat_trend_no_goal_reads_neutral(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.0,
            "ci_low_kg_per_week": -0.1,
            "ci_high_kg_per_week": 0.1,
        }
        result = _weight_window_meaning(80.0, trend, None, None)
        assert result["tone"] == "neutral"

    def test_losing_without_red_flag_reads_good(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.5,
            "ci_low_kg_per_week": -0.8,
            "ci_high_kg_per_week": -0.2,
        }
        result = _weight_window_meaning(80.0, trend, 77.0, {"red_flag": False})
        assert result["tone"] == "good"
        assert "losing" in result["headline"]
        assert "0.5kg/week" in result["headline"]

    def test_losing_with_red_flag_downgrades_to_neutral_and_warns(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.1,
            "ci_low_kg_per_week": -0.15,
            "ci_high_kg_per_week": -0.05,
        }
        result = _weight_window_meaning(80.0, trend, 77.0, {"red_flag": True})
        assert result["tone"] == "neutral"
        assert "won't make weight in time" in result["headline"]

    def test_gaining_is_always_bad_even_if_under_limit(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.5,
            "ci_low_kg_per_week": 0.2,
            "ci_high_kg_per_week": 0.8,
        }
        result = _weight_window_meaning(75.0, trend, 77.0, None)
        assert result["tone"] == "bad"
        assert "gaining" in result["headline"]
        assert "0.5kg/week" in result["headline"]


class TestHrvRhrWindowMeaning:
    """Direct unit tests -- both reuse `baselines.classify_deviation()`,
    the same +-1 SD rule `compute_hrv_baseline()`/`compute_rhr_baseline()`
    apply to their own latest observation.
    """

    def test_hrv_no_data(self) -> None:
        assert _hrv_window_meaning(None, {"confidence": "insufficient_data"})["tone"] == "unknown"

    def test_hrv_baseline_not_full_yet(self) -> None:
        result = _hrv_window_meaning(85.0, {"confidence": "provisional"})
        assert result["tone"] == "unknown"
        assert "not enough recovery-signal history" in result["headline"]

    def test_hrv_high(self) -> None:
        baseline = {"confidence": "full", "baseline_median": 90.0, "baseline_sd": 5.0}
        result = _hrv_window_meaning(100.0, baseline)  # +2 SD
        assert result["tone"] == "good"
        assert "above your normal range" in result["headline"]

    def test_hrv_low(self) -> None:
        baseline = {"confidence": "full", "baseline_median": 90.0, "baseline_sd": 5.0}
        result = _hrv_window_meaning(80.0, baseline)  # -2 SD
        assert result["tone"] == "bad"
        assert "below your normal range" in result["headline"]

    def test_hrv_balanced(self) -> None:
        baseline = {"confidence": "full", "baseline_median": 90.0, "baseline_sd": 5.0}
        result = _hrv_window_meaning(91.0, baseline)  # +0.2 SD
        assert result["tone"] == "neutral"
        assert "right around your normal range" in result["headline"]

    def test_rhr_no_data(self) -> None:
        assert _rhr_window_meaning(None, {"confidence": "insufficient_data"})["tone"] == "unknown"

    def test_rhr_high_is_bad(self) -> None:
        baseline = {"confidence": "full", "baseline_median": 50.0, "baseline_sd": 3.0}
        result = _rhr_window_meaning(58.0, baseline)  # ~+2.67 SD
        assert result["tone"] == "bad"
        assert "a bit elevated" in result["headline"]

    def test_rhr_low_is_good(self) -> None:
        baseline = {"confidence": "full", "baseline_median": 50.0, "baseline_sd": 3.0}
        result = _rhr_window_meaning(44.0, baseline)  # -2 SD
        assert result["tone"] == "good"
        assert "lower than your normal range" in result["headline"]


class TestSleepTotalWindowMeaning:
    def test_no_data(self) -> None:
        assert _sleep_total_window_meaning(None)["tone"] == "unknown"

    def test_short_sleep_reads_bad(self) -> None:
        result = _sleep_total_window_meaning(360.0)  # 6h00m
        assert result["tone"] == "bad"
        assert "under the 7-9 hour range" in result["headline"]
        assert "6h00m" in result["headline"]

    def test_in_band_reads_good(self) -> None:
        result = _sleep_total_window_meaning(480.0)  # 8h00m
        assert result["tone"] == "good"
        assert "right in the 7-9 hour range" in result["headline"]

    def test_long_sleep_reads_neutral(self) -> None:
        result = _sleep_total_window_meaning(600.0)  # 10h00m
        assert result["tone"] == "neutral"
        assert "above the usual 7-9 hour range" in result["headline"]


class TestBodyFatPctWindowMeaning:
    """Direct unit tests of `_body_fat_pct_window_meaning()` -- added
    2026-09-11, mirrors `_weight_window_meaning()`'s trend logic but with NO
    target-body-fat-% comparison clause (no such target is decided yet).
    """

    def test_no_data(self) -> None:
        result = _body_fat_pct_window_meaning(None, {"confidence": "insufficient_data"})
        assert result == {"tone": "unknown", "headline": "No body-fat readings in this window yet."}

    def test_trend_not_full_yet(self) -> None:
        result = _body_fat_pct_window_meaning(22.0, {"confidence": "insufficient_data"})
        assert result["tone"] == "unknown"
        assert "22.0% body fat" in result["headline"]
        assert "not enough recent readings" in result["headline"]

    def test_flat_trend_reads_neutral(self) -> None:
        trend = {
            "confidence": "full",
            "slope_pct_per_week": 0.0,
            "ci_low_pct_per_week": -0.1,
            "ci_high_pct_per_week": 0.1,
        }
        result = _body_fat_pct_window_meaning(22.0, trend)
        assert result["tone"] == "neutral"
        assert "holding steady" in result["headline"]

    def test_declining_reads_good(self) -> None:
        trend = {
            "confidence": "full",
            "slope_pct_per_week": -0.5,
            "ci_low_pct_per_week": -0.8,
            "ci_high_pct_per_week": -0.2,
        }
        result = _body_fat_pct_window_meaning(22.0, trend)
        assert result["tone"] == "good"
        assert "trending down" in result["headline"]
        assert "0.5 points a week" in result["headline"]

    def test_rising_reads_bad(self) -> None:
        trend = {
            "confidence": "full",
            "slope_pct_per_week": 0.4,
            "ci_low_pct_per_week": 0.1,
            "ci_high_pct_per_week": 0.7,
        }
        result = _body_fat_pct_window_meaning(22.0, trend)
        assert result["tone"] == "bad"
        assert "trending up" in result["headline"]
        assert "0.4 points a week" in result["headline"]

    def test_never_mentions_a_target_body_fat_percentage(self) -> None:
        # Locks in the explicit scoping decision: no target-comparison
        # clause exists yet anywhere in this function's output.
        trend = {
            "confidence": "full",
            "slope_pct_per_week": -0.5,
            "ci_low_pct_per_week": -0.8,
            "ci_high_pct_per_week": -0.2,
        }
        result = _body_fat_pct_window_meaning(22.0, trend)
        for banned in ("target", "goal", "division"):
            assert banned not in result["headline"].lower()


class TestFatMassWindowMeaning:
    """Direct unit tests of `_fat_mass_window_meaning()` -- reuses
    `weight_trend_ols()`'s own kg-labeled field names since fat mass really
    is measured in kg.
    """

    def test_no_data(self) -> None:
        result = _fat_mass_window_meaning(None, {"confidence": "insufficient_data"})
        assert result["tone"] == "unknown"
        assert "fat mass" in result["headline"]

    def test_trend_not_full_yet(self) -> None:
        result = _fat_mass_window_meaning(17.6, {"confidence": "insufficient_data"})
        assert result["tone"] == "unknown"
        assert "17.6kg of fat mass" in result["headline"]

    def test_flat_trend_reads_neutral(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.0,
            "ci_low_kg_per_week": -0.05,
            "ci_high_kg_per_week": 0.05,
        }
        result = _fat_mass_window_meaning(17.6, trend)
        assert result["tone"] == "neutral"
        assert "holding steady" in result["headline"]

    def test_declining_reads_good_and_calls_it_real_fat_loss(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.3,
            "ci_low_kg_per_week": -0.5,
            "ci_high_kg_per_week": -0.1,
        }
        result = _fat_mass_window_meaning(17.6, trend)
        assert result["tone"] == "good"
        assert "trending down" in result["headline"]
        assert "0.3kg/week" in result["headline"]
        assert "real fat loss" in result["headline"]

    def test_rising_reads_bad(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.3,
            "ci_low_kg_per_week": 0.1,
            "ci_high_kg_per_week": 0.5,
        }
        result = _fat_mass_window_meaning(17.6, trend)
        assert result["tone"] == "bad"
        assert "trending up" in result["headline"]


class TestReadinessWeakestComponent:
    """`_readiness_weakest_component()` reads real, already-persisted
    `derived_daily.inputs_json` rows -- fetched via a real query, not a
    hand-built `sqlite3.Row`, so this exercises the exact same shape the
    real code sees.
    """

    def _rows(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT date, value, confidence, n_days, inputs_json FROM derived_daily "
            "WHERE metric_name = 'readiness_score' ORDER BY date"
        ).fetchall()

    def test_identifies_sleep_when_consistently_worst(self, conn: sqlite3.Connection) -> None:
        components = {
            "hrv": {"score": 70.0},
            "rhr": {"score": 65.0},
            "sleep": {"score": 20.0},
            "subjective": {"score": 80.0},
        }
        for i in range(READINESS_MIN_DAYS_FOR_WEAK_COMPONENT):
            _write_derived(conn, f"2026-08-{20 + i}", 60.0, "partial", components)
        assert _readiness_weakest_component(self._rows(conn)) == "sleep"

    def test_switches_to_hrv_when_hrv_is_worst_instead(self, conn: sqlite3.Connection) -> None:
        components = {
            "hrv": {"score": 15.0},
            "rhr": {"score": 65.0},
            "sleep": {"score": 70.0},
            "subjective": {"score": 80.0},
        }
        for i in range(READINESS_MIN_DAYS_FOR_WEAK_COMPONENT):
            _write_derived(conn, f"2026-08-{20 + i}", 60.0, "partial", components)
        assert _readiness_weakest_component(self._rows(conn)) == "hrv"

    def test_none_below_the_minimum_real_days(self, conn: sqlite3.Connection) -> None:
        components = {"sleep": {"score": 10.0}, "hrv": {"score": 70.0}}
        for i in range(READINESS_MIN_DAYS_FOR_WEAK_COMPONENT - 1):
            _write_derived(conn, f"2026-08-{20 + i}", 60.0, "partial", components)
        assert _readiness_weakest_component(self._rows(conn)) is None

    def test_rows_with_no_inputs_json_are_ignored_not_crashed_on(
        self, conn: sqlite3.Connection
    ) -> None:
        for i in range(READINESS_MIN_DAYS_FOR_WEAK_COMPONENT):
            _write_derived(conn, f"2026-08-{20 + i}", 60.0, "partial")  # no components
        assert _readiness_weakest_component(self._rows(conn)) is None


class TestReadinessWindowMeaningWiring:
    """End-to-end through `build_trends_payload()` -- confirms the weakest-
    component read and the band classification actually reach the real
    payload, not just the isolated helper functions above.
    """

    def _seed_days(self, conn: sqlite3.Connection, n: int, components: dict, value: float) -> None:
        for i in range(n):
            _write_derived(conn, f"2026-08-{20 + i}", value, "partial", components)
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date=f"2026-08-{20 + n - 1}", weight_kg=80.0).to_row(),
            ["date"],
        )

    def test_amber_band_names_sleep_as_the_reason(self, conn: sqlite3.Connection) -> None:
        components = {
            "hrv": {"score": 70.0},
            "rhr": {"score": 65.0},
            "sleep": {"score": 20.0},
            "subjective": {"score": 80.0},
        }
        self._seed_days(conn, READINESS_MIN_DAYS_FOR_WEAK_COMPONENT, components, 60.0)
        payload = build_trends_payload(conn, 90, _CONFIG)
        meaning = payload["readiness"]["meaning"]
        assert meaning["tone"] == "neutral"
        assert "okay, but could be better" in meaning["headline"]
        assert "slept more consistently" in meaning["headline"]

    def test_amber_band_switches_reason_to_recovery_when_hrv_is_worst(
        self, conn: sqlite3.Connection
    ) -> None:
        components = {
            "hrv": {"score": 15.0},
            "rhr": {"score": 65.0},
            "sleep": {"score": 70.0},
            "subjective": {"score": 80.0},
        }
        self._seed_days(conn, READINESS_MIN_DAYS_FOR_WEAK_COMPONENT, components, 60.0)
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert "gave your body more recovery time" in payload["readiness"]["meaning"]["headline"]

    def test_insufficient_component_detail_says_so_honestly(self, conn: sqlite3.Connection) -> None:
        components = {"sleep": {"score": 10.0}}
        self._seed_days(conn, READINESS_MIN_DAYS_FOR_WEAK_COMPONENT - 2, components, 60.0)
        payload = build_trends_payload(conn, 90, _CONFIG)
        meaning = payload["readiness"]["meaning"]
        assert meaning["tone"] == "neutral"
        assert "Not enough day-by-day detail yet" in meaning["headline"]

    def test_green_band_never_mentions_a_weak_component(self, conn: sqlite3.Connection) -> None:
        components = {
            "hrv": {"score": 90.0},
            "rhr": {"score": 85.0},
            "sleep": {"score": 60.0},
            "subjective": {"score": 95.0},
        }
        self._seed_days(conn, READINESS_MIN_DAYS_FOR_WEAK_COMPONENT, components, 80.0)
        payload = build_trends_payload(conn, 90, _CONFIG)
        meaning = payload["readiness"]["meaning"]
        assert meaning["tone"] == "good"
        assert "could be better" not in meaning["headline"]


class TestReadinessHistory:
    def _seed_daily_metrics(self, conn: sqlite3.Connection, date: str) -> None:
        # build_trends_payload's window cutoff is anchored on daily_metrics'
        # own max date -- readiness history alone isn't enough to produce a
        # non-empty payload, same as every other series on this page.
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date=date, weight_kg=80.0).to_row(), ["date"]
        )

    def test_readiness_history_included_with_confidence(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-27", 54.1, "partial")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        raw = payload["readiness"]["raw"]
        assert [(r["date"], r["value"], r["confidence"]) for r in raw] == [
            ("2026-08-27", 54.1, "partial"),
            ("2026-08-28", 55.8, "full"),
        ]

    def test_coverage_summary_counts_each_confidence_level(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-26", 50.0, "partial")
        _write_derived(conn, "2026-08-27", 54.1, "partial")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["readiness"]["coverage_summary"] == {"partial": 2, "full": 1}

    def test_insufficient_data_rows_excluded_by_null_value(self, conn: sqlite3.Connection) -> None:
        # store_derived_metrics() always writes a row per metric per date --
        # even an insufficient_data one has value=NULL, and NULL isn't a
        # real readiness number to chart.
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-27", None, "insufficient_data")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90, _CONFIG)
        assert [r["date"] for r in payload["readiness"]["raw"]] == ["2026-08-28"]

    def test_readiness_history_respects_the_window_cutoff(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-01-01", 60.0, "full")  # well outside a 30-day window
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 30, _CONFIG)
        assert [r["date"] for r in payload["readiness"]["raw"]] == ["2026-08-28"]

    def test_other_metric_names_never_leak_into_readiness_history(
        self, conn: sqlite3.Connection
    ) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        db_module.upsert(
            conn,
            "derived_daily",
            {"date": "2026-08-28", "metric_name": "ctl", "value": 12.3, "confidence": "stale"},
            ["date", "metric_name"],
            touch_column="computed_at",
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        assert payload["readiness"]["raw"] == []


class TestInsights:
    def test_always_includes_the_four_core_metrics(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        metrics = {i["metric"] for i in payload["insights"]}
        assert {"weight", "sleep", "hrv", "rhr"} <= metrics

    def test_no_data_anywhere_gives_unknown_tone_not_a_crash(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=78.5).to_row(), ["date"]
        )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        assert by_metric["sleep"]["tone"] == "unknown"
        assert by_metric["hrv"]["tone"] == "unknown"
        assert by_metric["rhr"]["tone"] == "unknown"

    def test_real_losing_weight_trend_produces_a_good_tone_insight(
        self, conn: sqlite3.Connection
    ) -> None:
        import datetime

        start = datetime.date(2026, 8, 1)
        for i in range(25):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, weight_kg=80.0 - i * 0.05).to_row(),
                ["date"],
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        assert by_metric["weight"]["tone"] == "good"
        assert "losing weight" in by_metric["weight"]["headline"].lower()

    def test_insights_are_not_windowed_by_the_chart_selector(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real weight history goes back further than a 30-day chart window,
        # but the insight itself should still use the full 21-day OLS trend
        # regardless of what window the charts above are set to.
        import datetime

        start = datetime.date(2026, 6, 1)
        for i in range(60):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, weight_kg=80.0 - i * 0.05).to_row(),
                ["date"],
            )
        payload_30 = build_trends_payload(conn, 30, _CONFIG)
        payload_365 = build_trends_payload(conn, 365, _CONFIG)
        weight_30 = next(i for i in payload_30["insights"] if i["metric"] == "weight")
        weight_365 = next(i for i in payload_365["insights"] if i["metric"] == "weight")
        assert weight_30 == weight_365

    def test_headline_and_detail_never_say_bare_hrv_or_rhr(self, conn: sqlite3.Connection) -> None:
        # Real gap found 2026-08-31: hrv_insight()'s headline literally said
        # "HRV" in every branch, inconsistent with rhr_insight() (which
        # correctly spells out "resting heart rate") -- same "no fluff no
        # acronyms" discipline Training's own acronym-lock test already
        # enforces for ctl/atl/tsb/monotony. Checked only against the
        # user-facing headline/detail prose, not the internal "metric" key
        # (which is a real, intentional identifier the frontend keys icons
        # off of, e.g. "hrv"/"rhr" in frontend/src/types/trends.ts -- not
        # prose a reader ever sees).
        #
        # 2026-09-09: extended to also cover the new per-chart window
        # "meaning" text (series/sleep_total/readiness) -- the exact same
        # discipline, just a second real place it could regress.
        import datetime
        import re

        start = datetime.date(2026, 1, 1)
        for i in range(65):
            d = (start + datetime.timedelta(days=i)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, hrv_overnight_ms=90.0, resting_hr=50.0).to_row(),
                ["date"],
            )
        payload = build_trends_payload(conn, 90, _CONFIG)
        by_metric = {i["metric"]: i for i in payload["insights"]}
        # Confirms the "full baseline" branches (not the seed/insufficient
        # placeholder text) actually ran -- a constant series deviates 0 SD
        # from its own baseline, i.e. "balanced"/neutral.
        assert by_metric["hrv"]["tone"] == "neutral"
        assert by_metric["rhr"]["tone"] == "neutral"
        assert payload["series"]["hrv_overnight_ms"]["meaning"]["tone"] == "neutral"
        assert payload["series"]["resting_hr"]["meaning"]["tone"] == "neutral"

        texts = [
            " ".join(filter(None, [insight.get("headline"), insight.get("detail")]))
            for insight in payload["insights"]
        ]
        texts.extend(series["meaning"]["headline"] for series in payload["series"].values())
        texts.append(payload["sleep_total"]["meaning"]["headline"])
        texts.append(payload["readiness"]["meaning"]["headline"])

        for text in texts:
            assert not re.search(r"\bhrv\b", text, re.IGNORECASE), text
            assert not re.search(r"\brhr\b", text, re.IGNORECASE), text
