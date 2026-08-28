from __future__ import annotations

from datetime import date, timedelta

import pytest

from health_os.metrics.baselines import (
    compute_hrv_baseline,
    compute_rhr_baseline,
    compute_sleep_debt,
)


def _dated(values: list[float], start: str = "2026-01-01") -> list[tuple[str, float]]:
    start_date = date.fromisoformat(start)
    return [((start_date + timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]


def _identical_plus_outlier(n: int, common: float, outlier: float) -> list[float]:
    """n values total: (n-1) copies of `common`, then `outlier` last.

    Closed form (derived independently, not from the implementation): for this
    exact construction, median == common (the single outlier can't move the
    middle order statistic when n-1 >= 2), and
        deviation_sd = (outlier - common) / pstdev = sign(outlier-common) * n / sqrt(n-1)
    regardless of the outlier's exact magnitude - a clean, exactly-checkable
    result instead of an approximation.
    """
    return [common] * (n - 1) + [outlier]


class TestComputeHrvBaseline:
    def test_insufficient_data_below_21_days(self) -> None:
        obs = _dated([90.0] * 20)
        result = compute_hrv_baseline(obs)
        assert result["confidence"] == "insufficient_data"
        assert result["baseline_method"] == "insufficient_data"

    def test_seed_phase_green(self) -> None:
        obs = _dated([95.0] * 25)  # 21-59 days -> seed phase; >90 -> balanced
        result = compute_hrv_baseline(obs)
        assert result["baseline_method"] == "seed"
        assert result["confidence"] == "provisional"
        assert result["status"] == "balanced"

    def test_seed_phase_capped(self) -> None:
        obs = _dated([80.0] * 25)  # 75-85 -> capped
        result = compute_hrv_baseline(obs)
        assert result["status"] == "capped"

    def test_seed_phase_low(self) -> None:
        obs = _dated([60.0] * 25)  # below 75 -> low
        result = compute_hrv_baseline(obs)
        assert result["status"] == "low"

    def test_seed_phase_undocumented_gap_defaults_balanced(self) -> None:
        obs = _dated([87.0] * 25)  # between 85 and 90, not specified in the brief
        result = compute_hrv_baseline(obs)
        assert result["status"] == "balanced"

    def test_computed_phase_exact_closed_form_high(self) -> None:
        # 59 days @ 80.0, latest = 90.0. median stays 80 exactly; deviation_sd
        # = 60/sqrt(59) (derived above), which is > 1 -> "high".
        values = _identical_plus_outlier(60, common=80.0, outlier=90.0)
        result = compute_hrv_baseline(_dated(values))
        assert result["baseline_method"] == "computed"
        assert result["confidence"] == "full"
        assert result["baseline_median"] == pytest.approx(80.0)
        assert result["deviation_sd"] == pytest.approx(60 / (59**0.5))
        assert result["status"] == "high"

    def test_computed_phase_exact_closed_form_low(self) -> None:
        values = _identical_plus_outlier(60, common=80.0, outlier=70.0)
        result = compute_hrv_baseline(_dated(values))
        assert result["deviation_sd"] == pytest.approx(-60 / (59**0.5))
        assert result["status"] == "low"

    def test_computed_phase_balanced_when_at_baseline(self) -> None:
        obs = _dated([80.0] * 60)
        result = compute_hrv_baseline(obs)
        assert result["deviation_sd"] == pytest.approx(0.0)
        assert result["status"] == "balanced"

    def test_switches_from_seed_to_computed_exactly_at_60_days(self) -> None:
        result_59 = compute_hrv_baseline(_dated([90.0] * 59))
        result_60 = compute_hrv_baseline(_dated([90.0] * 60))
        assert result_59["baseline_method"] == "seed"
        assert result_60["baseline_method"] == "computed"


class TestComputeRhrBaseline:
    def test_insufficient_data_below_21_days(self) -> None:
        result = compute_rhr_baseline(_dated([50.0] * 20))
        assert result["confidence"] == "insufficient_data"

    def test_exact_closed_form_high(self) -> None:
        values = _identical_plus_outlier(60, common=50.0, outlier=60.0)
        result = compute_rhr_baseline(_dated(values))
        assert result["deviation_sd"] == pytest.approx(60 / (59**0.5))
        assert result["status"] == "high"

    def test_sustained_rise_flag_true_for_3_consecutive_high_days(self) -> None:
        # 60 stable days at 50, then 3 clearly-elevated days at 70.
        values = [50.0] * 60 + [70.0, 70.0, 70.0]
        result = compute_rhr_baseline(_dated(values))
        assert result["sustained_rise_flag"] is True

    def test_sustained_rise_flag_false_for_only_2_high_days(self) -> None:
        values = [50.0] * 60 + [70.0, 70.0]
        result = compute_rhr_baseline(_dated(values))
        assert result["sustained_rise_flag"] is False

    def test_sustained_rise_flag_false_when_not_consecutive(self) -> None:
        values = [50.0] * 60 + [70.0, 50.0, 70.0]
        result = compute_rhr_baseline(_dated(values))
        assert result["sustained_rise_flag"] is False


class TestComputeSleepDebt:
    def test_empty_observations(self) -> None:
        result = compute_sleep_debt([])
        assert result["confidence"] == "insufficient_data"
        assert result["debt_hours"] is None

    def test_hand_computed_partial_window(self) -> None:
        # 3 real nights: 6h, 6h, 10h (in minutes). debt = 2 + 2 + (-2) = 2.0h.
        obs = _dated([360.0, 360.0, 600.0])
        result = compute_sleep_debt(obs)
        assert result["debt_hours"] == pytest.approx(2.0)
        assert result["n_days"] == 3
        assert result["confidence"] == "partial"

    def test_full_window_zero_debt(self) -> None:
        obs = _dated([480.0] * 14)  # exactly 8h every night
        result = compute_sleep_debt(obs)
        assert result["debt_hours"] == pytest.approx(0.0)
        assert result["confidence"] == "full"

    def test_window_excludes_nights_before_cutoff(self) -> None:
        # 20 nights total; only the trailing 14 calendar days should count.
        obs = _dated([480.0] * 20)
        result = compute_sleep_debt(obs, window_days=14)
        assert result["n_days"] == 14

    def test_surplus_is_negative_debt(self) -> None:
        obs = _dated([600.0] * 14)  # 10h every night -> surplus
        result = compute_sleep_debt(obs)
        assert result["debt_hours"] < 0
