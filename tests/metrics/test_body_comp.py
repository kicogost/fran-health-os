from __future__ import annotations

import pytest

from health_os.metrics.body_comp import (
    comp_countdown,
    compute_weight_ewma,
    weight_trend_ols,
)


class TestComputeWeightEwma:
    def test_hand_computed_three_points(self) -> None:
        # alpha = 2/(7+1) = 0.25
        # ewma1 = 80.0
        # ewma2 = 0.25*79.0 + 0.75*80.0 = 19.75 + 60.0 = 79.75
        # ewma3 = 0.25*78.0 + 0.75*79.75 = 19.5 + 59.8125 = 79.3125
        result = compute_weight_ewma(
            [("2026-08-01", 80.0), ("2026-08-02", 79.0), ("2026-08-03", 78.0)]
        )
        dates = [d for d, _ in result]
        values = [v for _, v in result]
        assert dates == ["2026-08-01", "2026-08-02", "2026-08-03"]
        assert values == pytest.approx([80.0, 79.75, 79.3125])

    def test_empty_input(self) -> None:
        assert compute_weight_ewma([]) == []

    def test_single_point_returns_itself(self) -> None:
        assert compute_weight_ewma([("2026-08-01", 80.0)]) == [("2026-08-01", 80.0)]

    def test_custom_span(self) -> None:
        # alpha = 2/(3+1) = 0.5
        # ewma1 = 80.0; ewma2 = 0.5*79.0 + 0.5*80.0 = 79.5
        result = compute_weight_ewma([("2026-08-01", 80.0), ("2026-08-02", 79.0)], span_days=3)
        assert [v for _, v in result] == pytest.approx([80.0, 79.5])


class TestWeightTrendOls:
    def test_perfect_linear_decline_hand_computed(self) -> None:
        # 5 consecutive days, exactly -0.1 kg/day = -0.7 kg/week. A perfect fit
        # has zero standard error, so the 95% CI collapses to the point estimate.
        observations = [
            ("2026-08-01", 80.0),
            ("2026-08-02", 79.9),
            ("2026-08-03", 79.8),
            ("2026-08-04", 79.7),
            ("2026-08-05", 79.6),
        ]
        result = weight_trend_ols(observations, window_days=21, min_points=5)
        assert result["confidence"] == "full"
        assert result["n"] == 5
        assert result["slope_kg_per_week"] == pytest.approx(-0.7, abs=1e-6)
        assert result["ci_low_kg_per_week"] == pytest.approx(-0.7, abs=1e-4)
        assert result["ci_high_kg_per_week"] == pytest.approx(-0.7, abs=1e-4)

    def test_flat_weight_gives_zero_slope(self) -> None:
        observations = [(f"2026-08-{d:02d}", 79.0) for d in range(1, 6)]
        result = weight_trend_ols(observations, min_points=5)
        assert result["slope_kg_per_week"] == pytest.approx(0.0, abs=1e-9)

    def test_insufficient_data_below_min_points(self) -> None:
        observations = [("2026-08-01", 80.0), ("2026-08-02", 79.9), ("2026-08-03", 79.8)]
        result = weight_trend_ols(observations, min_points=5)
        assert result["confidence"] == "insufficient_data"
        assert result["slope_kg_per_week"] is None
        assert result["n"] == 3

    def test_empty_observations(self) -> None:
        result = weight_trend_ols([])
        assert result["confidence"] == "insufficient_data"
        assert result["n"] == 0

    def test_window_excludes_old_points(self) -> None:
        # 10 days of history, but a 3-day window should only see the last 3.
        observations = [(f"2026-08-{d:02d}", 80.0 - d * 0.1) for d in range(1, 11)]
        result = weight_trend_ols(observations, window_days=3, min_points=3)
        assert result["n"] == 3

    def test_never_computes_ci_below_3_points_even_if_min_points_lower(self) -> None:
        observations = [("2026-08-01", 80.0), ("2026-08-02", 79.9)]
        result = weight_trend_ols(observations, min_points=1)
        assert result["confidence"] == "insufficient_data"


class TestCompCountdown:
    def test_on_track_not_red(self) -> None:
        result = comp_countdown(
            current_weight_kg=79.0,
            trend_slope_kg_per_week=-0.25,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-08-23",  # exactly 56 days = 8 weeks before comp
        )
        assert result["kg_remaining"] == pytest.approx(2.0)
        assert result["weeks_remaining"] == pytest.approx(8.0)
        assert result["required_kg_per_week"] == pytest.approx(0.25)
        assert result["actual_kg_per_week"] == pytest.approx(0.25)
        assert result["red_flag"] is False

    def test_red_flag_when_required_exceeds_threshold(self) -> None:
        result = comp_countdown(
            current_weight_kg=85.0,
            trend_slope_kg_per_week=None,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-10-04",  # 14 days = 2 weeks before comp
        )
        assert result["required_kg_per_week"] == pytest.approx(4.0)
        assert result["red_flag"] is True

    def test_already_under_limit_gives_negative_required(self) -> None:
        result = comp_countdown(
            current_weight_kg=76.5,
            trend_slope_kg_per_week=-0.1,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-09-18",
        )
        assert result["kg_remaining"] < 0
        assert result["required_kg_per_week"] < 0
        assert result["red_flag"] is False

    def test_comp_date_reached_gives_none_required(self) -> None:
        result = comp_countdown(
            current_weight_kg=78.0,
            trend_slope_kg_per_week=-0.2,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-10-18",
        )
        assert result["weeks_remaining"] == 0
        assert result["required_kg_per_week"] is None

    def test_missing_trend_leaves_actual_none_but_required_still_computed(self) -> None:
        result = comp_countdown(
            current_weight_kg=79.0,
            trend_slope_kg_per_week=None,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-08-23",
        )
        assert result["actual_kg_per_week"] is None
        assert result["required_kg_per_week"] is not None

    def test_custom_red_line(self) -> None:
        result = comp_countdown(
            current_weight_kg=79.0,
            trend_slope_kg_per_week=None,
            comp_date="2026-10-18",
            weight_limit_kg=77.0,
            today="2026-08-23",
            red_line_kg_per_week=0.1,
        )
        assert result["required_kg_per_week"] == pytest.approx(0.25)
        assert result["red_flag"] is True
