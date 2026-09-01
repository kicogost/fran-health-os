from __future__ import annotations

from health_os.metrics.insights import (
    consistency_insight,
    correlation_insight,
    fitness_trend_insight,
    freshness_insight,
    hrv_insight,
    rhr_insight,
    sleep_insight,
    weight_insight,
)


class TestWeightInsight:
    def test_insufficient_data_gives_unknown_tone(self) -> None:
        result = weight_insight({"confidence": "insufficient_data", "slope_kg_per_week": None})
        assert result["tone"] == "unknown"
        assert "not enough" in result["headline"].lower()

    def test_ci_straddling_zero_reads_as_steady(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.1,
            "ci_low_kg_per_week": -0.3,
            "ci_high_kg_per_week": 0.5,
        }
        result = weight_insight(trend)
        assert result["tone"] == "neutral"
        assert "steady" in result["headline"].lower()

    def test_clearly_losing_weight_is_good_tone(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.5,
            "ci_low_kg_per_week": -0.8,
            "ci_high_kg_per_week": -0.2,
        }
        result = weight_insight(trend)
        assert result["tone"] == "good"
        assert "losing weight" in result["headline"].lower()
        assert "0.5" in result["headline"]

    def test_clearly_gaining_weight_is_bad_tone(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": 0.4,
            "ci_low_kg_per_week": 0.1,
            "ci_high_kg_per_week": 0.7,
        }
        result = weight_insight(trend)
        assert result["tone"] == "bad"
        assert "gaining weight" in result["headline"].lower()

    def test_red_flag_comp_countdown_adds_warning_detail(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.2,
            "ci_low_kg_per_week": -0.4,
            "ci_high_kg_per_week": -0.05,
        }
        result = weight_insight(trend, comp_countdown={"red_flag": True})
        assert result["detail"] is not None
        assert "won't make weight" in result["detail"].lower()

    def test_on_track_comp_countdown_adds_positive_detail(self) -> None:
        trend = {
            "confidence": "full",
            "slope_kg_per_week": -0.2,
            "ci_low_kg_per_week": -0.4,
            "ci_high_kg_per_week": -0.05,
        }
        result = weight_insight(trend, comp_countdown={"red_flag": False})
        assert result["detail"] == "That's on track for your competition weight."


class TestSleepInsight:
    def test_insufficient_data_gives_unknown_tone(self) -> None:
        result = sleep_insight({"confidence": "insufficient_data", "debt_hours": None}, None, None)
        assert result["tone"] == "unknown"

    def test_surplus_reads_as_sleeping_great(self) -> None:
        debt = {"confidence": "full", "debt_hours": -5.0}
        result = sleep_insight(debt, 8.0, 7.5)
        assert result["tone"] == "good"
        assert "sleeping great" in result["headline"].lower()
        assert "8h00m" in result["headline"]

    def test_near_zero_debt_reads_as_about_right(self) -> None:
        debt = {"confidence": "full", "debt_hours": 1.0}
        result = sleep_insight(debt, 7.2, 7.2)
        assert result["tone"] == "neutral"

    def test_large_deficit_reads_as_under_sleeping(self) -> None:
        debt = {"confidence": "full", "debt_hours": 8.0}
        result = sleep_insight(debt, 6.0, 6.0)
        assert result["tone"] == "bad"
        assert "under-sleeping" in result["headline"].lower()

    def test_week_over_week_improvement_noted(self) -> None:
        debt = {"confidence": "full", "debt_hours": 0.0}
        result = sleep_insight(debt, 7.5, 6.5)
        assert result["detail"] is not None
        assert "up from" in result["detail"].lower()

    def test_small_week_over_week_change_not_mentioned(self) -> None:
        debt = {"confidence": "full", "debt_hours": 0.0}
        result = sleep_insight(debt, 7.3, 7.2)
        assert result["detail"] is None


class TestHrvInsight:
    def test_seed_phase_gives_unknown_tone(self) -> None:
        result = hrv_insight({"confidence": "provisional", "status": "balanced"})
        assert result["tone"] == "unknown"
        assert "building" in result["headline"].lower()

    def test_high_is_good(self) -> None:
        result = hrv_insight({"confidence": "full", "status": "high", "value": 95.0})
        assert result["tone"] == "good"
        assert "95" in result["headline"]

    def test_low_is_bad(self) -> None:
        result = hrv_insight({"confidence": "full", "status": "low", "value": 70.0})
        assert result["tone"] == "bad"

    def test_balanced_is_neutral(self) -> None:
        result = hrv_insight({"confidence": "full", "status": "balanced", "value": 90.0})
        assert result["tone"] == "neutral"


class TestRhrInsight:
    def test_insufficient_data_gives_unknown_tone(self) -> None:
        result = rhr_insight({"confidence": "insufficient_data", "status": "insufficient_data"})
        assert result["tone"] == "unknown"

    def test_high_is_bad_tone_inverted_vs_hrv(self) -> None:
        result = rhr_insight({"confidence": "full", "status": "high", "value": 55.0})
        assert result["tone"] == "bad"

    def test_low_is_good_tone(self) -> None:
        result = rhr_insight({"confidence": "full", "status": "low", "value": 45.0})
        assert result["tone"] == "good"

    def test_sustained_rise_adds_detail(self) -> None:
        result = rhr_insight(
            {"confidence": "full", "status": "high", "value": 55.0, "sustained_rise_flag": True}
        )
        assert result["detail"] is not None
        assert "3 days" in result["detail"]

    def test_no_sustained_flag_no_detail(self) -> None:
        result = rhr_insight(
            {"confidence": "full", "status": "high", "value": 55.0, "sustained_rise_flag": False}
        )
        assert result["detail"] is None


class TestCorrelationInsight:
    def test_not_significant_gives_none(self) -> None:
        assert correlation_insight({"confidence": "insufficient_data", "rho": None}) is None
        assert correlation_insight({"confidence": "not_significant", "rho": 0.1}) is None

    def test_significant_positive_uses_plain_pair_text(self) -> None:
        # "fatigue"/"sleep_total_min" -- neither field has inverted storage
        # polarity (see TestCorrelationInsightPolarity below for the pairs
        # that do), so this exercises plain pair-text substitution and the
        # positive-direction wording with no sign normalization in play.
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": 0.6,
                "n": 40,
                "x_name": "fatigue",
                "y_name": "sleep_total_min",
            }
        )
        assert result is not None
        assert "how tired you feel tracks how much you actually sleep" in result["headline"]
        assert "more one goes up" in result["headline"]
        assert "40 real days" in result["detail"]

    def test_significant_negative_describes_inverse_direction(self) -> None:
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": -0.5,
                "n": 35,
                "x_name": "stress",
                "y_name": "resting_hr",
            }
        )
        assert result is not None
        assert "the other tends to go down" in result["headline"]

    def test_unknown_pair_falls_back_to_raw_description(self) -> None:
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": 0.4,
                "n": 30,
                "x_name": "foo",
                "y_name": "bar",
                "description": "foo vs bar",
            }
        )
        assert result is not None
        assert "foo vs bar" in result["headline"]


class TestCorrelationInsightPolarity:
    """`sleep_quality` (1=best..10=worst) and `hooper_index` (4=excellent..
    40=terrible, migration 0002) are both stored on a "lower = better"
    scale, but their `_PLAIN_PAIR_TEXT` descriptions read naturally as
    "higher = better" to an English reader ("how well you say you slept,"
    "your daily wellness check-in"). Real bug found 2026-08-31: the
    direction sentence used raw `rho`'s sign directly, so a genuine,
    physiologically correct inverse relationship (worse sleep_quality SCORE
    <-> higher HRV, i.e. better sleep <-> higher HRV) rendered backwards --
    "when one goes up, the other tends to go down" reads as "better sleep ->
    worse HRV" to an English reader, the opposite of the true finding.
    """

    def test_sleep_quality_inverse_raw_rho_reads_as_moving_together(self) -> None:
        # Real scenario: better sleep -> higher HRV. Since sleep_quality is
        # stored worst-high (1=best), "better sleep" means a LOWER raw
        # score, so the real, physiologically correct raw correlation with
        # HRV is NEGATIVE.
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": -0.6,
                "n": 40,
                "x_name": "sleep_quality",
                "y_name": "hrv_overnight_ms",
            }
        )
        assert result is not None
        assert "how well you say you slept" in result["headline"]
        # Plain reading: "how well you slept" and "your HRV" should move
        # TOGETHER (better sleep, higher HRV) -- not "the other goes down."
        assert "the more one goes up, the more the other does too" in result["headline"]

    def test_hooper_index_inverse_raw_rho_reads_as_moving_together(self) -> None:
        # Real scenario: better daily wellness (lower hooper_index) goes
        # with a higher computed readiness_score (not inverted -- higher is
        # already better) -- the real, physiologically correct raw
        # correlation is NEGATIVE.
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": -0.5,
                "n": 35,
                "x_name": "hooper_index",
                "y_name": "readiness_score",
            }
        )
        assert result is not None
        assert "your daily wellness check-in" in result["headline"]
        assert "the more one goes up, the more the other does too" in result["headline"]

    def test_inverted_field_as_y_name_also_normalizes(self) -> None:
        # The normalization must apply regardless of which side of the pair
        # the inverted-polarity field lands on.
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": -0.5,
                "n": 30,
                "x_name": "readiness_score",
                "y_name": "hooper_index",
            }
        )
        assert result is not None
        assert "the more one goes up, the more the other does too" in result["headline"]

    def test_non_inverted_pair_unaffected_by_normalization(self) -> None:
        # Sanity check: a pair with neither field inverted (e.g. stress /
        # resting_hr) must read exactly off the raw rho sign, unchanged.
        result = correlation_insight(
            {
                "confidence": "significant",
                "rho": 0.5,
                "n": 30,
                "x_name": "stress",
                "y_name": "resting_hr",
            }
        )
        assert result is not None
        assert "the more one goes up, the more the other does too" in result["headline"]


def _ctl_series(last_value: float, *, n_days: int = 25, base_value: float = 20.0) -> list:
    """`n_days` consecutive dates ending today, all at `base_value` except
    the last, which is `last_value` -- exercises the "compare latest to
    ~21 days back" logic against a flat, easy-to-reason-about backdrop.
    """
    import datetime

    start = datetime.date(2026, 8, 30) - datetime.timedelta(days=n_days - 1)
    series = [((start + datetime.timedelta(days=i)).isoformat(), base_value) for i in range(n_days)]
    series[-1] = (series[-1][0], last_value)
    return series


class TestFitnessTrendInsight:
    def test_short_history_gives_unknown_tone(self) -> None:
        result = fitness_trend_insight(_ctl_series(20.0, n_days=5))
        assert result["tone"] == "unknown"

    def test_rising_ctl_is_good_tone(self) -> None:
        # +30% vs. the value 21 days back (base_value=20.0) -- well above
        # the 15% noise threshold.
        result = fitness_trend_insight(_ctl_series(26.0))
        assert result["tone"] == "good"
        assert "building" in result["headline"].lower()

    def test_falling_ctl_is_neutral_not_bad(self) -> None:
        result = fitness_trend_insight(_ctl_series(14.0))  # -30%
        assert result["tone"] == "neutral"
        assert "dipped" in result["headline"].lower()

    def test_small_change_reads_as_steady(self) -> None:
        result = fitness_trend_insight(_ctl_series(20.5))  # +2.5%, below threshold
        assert "steady" in result["headline"].lower()


class TestFreshnessInsight:
    def test_insufficient_data_gives_unknown(self) -> None:
        result = freshness_insight({"confidence": "insufficient_data", "z_score": None})
        assert result["tone"] == "unknown"
        assert result["band"] == "unknown"

    def test_very_negative_z_reads_as_fatigued(self) -> None:
        result = freshness_insight({"confidence": "full", "z_score": -2.0})
        assert result["band"] == "fatigued"
        assert result["tone"] == "bad"

    def test_near_zero_z_reads_as_normal(self) -> None:
        result = freshness_insight({"confidence": "full", "z_score": 0.0})
        assert result["band"] == "normal"
        assert result["tone"] == "neutral"

    def test_very_positive_z_reads_as_very_fresh(self) -> None:
        result = freshness_insight({"confidence": "full", "z_score": 2.5})
        assert result["band"] == "very_fresh"
        assert result["tone"] == "good"

    def test_mildly_negative_z_reads_as_tired(self) -> None:
        result = freshness_insight({"confidence": "full", "z_score": -1.0})
        assert result["band"] == "tired"

    def test_mildly_positive_z_reads_as_fresh(self) -> None:
        result = freshness_insight({"confidence": "full", "z_score": 1.0})
        assert result["band"] == "fresh"


class TestConsistencyInsight:
    def test_none_gives_unknown(self) -> None:
        result = consistency_insight(None)
        assert result["tone"] == "unknown"

    def test_insufficient_data_gives_unknown(self) -> None:
        result = consistency_insight({"confidence": "insufficient_data"})
        assert result["tone"] == "unknown"

    def test_zero_variance_reads_as_identical_days(self) -> None:
        result = consistency_insight({"confidence": "undefined_zero_variance"})
        assert "exact same" in result["headline"].lower()

    def test_high_monotony_flagged(self) -> None:
        result = consistency_insight({"confidence": "full", "flag_high_monotony": True})
        assert result["detail"] is not None
        assert "similar intensity" in result["headline"].lower()

    def test_healthy_mix_is_good_tone(self) -> None:
        result = consistency_insight({"confidence": "full", "flag_high_monotony": False})
        assert result["tone"] == "good"
