from __future__ import annotations

import pytest

from health_os.metrics.readiness import compute_readiness_score


class TestComputeReadinessScore:
    def test_no_components_gives_insufficient_data(self) -> None:
        result = compute_readiness_score()
        assert result["score"] is None
        assert result["confidence"] == "insufficient_data"
        assert result["coverage"] == 0.0

    def test_neutral_deviations_but_sleep_need_exactly_met(self) -> None:
        # hrv/rhr/tsb at 0 deviation and hooper at its midpoint all score 50
        # (symmetric components) -- but sleep is NOT symmetric: hitting your
        # 8h need with zero debt is the sleep component's ceiling (100), not
        # a neutral midpoint. Hand-computed: 0.35*50 + 0.25*100 + 0.15*50 +
        # 0.15*50 + 0.10*50 = 62.5. (Caught by a first draft of this test that
        # wrongly assumed sleep would also come out to 50 -- it's intentionally
        # not symmetric, see _sleep_component_score's docstring.)
        result = compute_readiness_score(
            hrv_deviation_sd=0.0,
            rhr_deviation_sd=0.0,
            last_night_sleep_hours=8.0,
            sleep_debt_hours=0.0,
            tsb_z_score=0.0,
            hooper_index=22.0,  # midpoint of the 4-40 range
        )
        assert result["components"]["sleep"]["score"] == pytest.approx(100.0)
        assert result["score"] == pytest.approx(62.5)
        assert result["confidence"] == "full"
        assert result["coverage"] == pytest.approx(1.0)

    def test_hrv_component_direction_and_clamp(self) -> None:
        # +2 SD (clamped) HRV alone, nothing else -> full weight on hrv,
        # score = 50 + 25*2 = 100.
        result = compute_readiness_score(hrv_deviation_sd=5.0)  # clamped to +2
        assert result["components"]["hrv"]["score"] == pytest.approx(100.0)
        assert result["score"] == pytest.approx(100.0)
        assert result["components"]["hrv"]["weight_used"] == pytest.approx(1.0)

    def test_rhr_component_is_inverted_vs_hrv(self) -> None:
        # Elevated RHR (positive deviation) should REDUCE readiness, opposite of HRV.
        result = compute_readiness_score(rhr_deviation_sd=2.0)
        assert result["components"]["rhr"]["score"] == pytest.approx(0.0)

    def test_tsb_component_direction_and_clamp(self) -> None:
        result = compute_readiness_score(tsb_z_score=-5.0)  # clamped to -2
        assert result["components"]["tsb"]["score"] == pytest.approx(0.0)

    def test_subjective_component_best_and_worst(self) -> None:
        best = compute_readiness_score(hooper_index=4.0)
        worst = compute_readiness_score(hooper_index=40.0)
        assert best["components"]["subjective"]["score"] == pytest.approx(100.0)
        assert worst["components"]["subjective"]["score"] == pytest.approx(0.0)

    def test_sleep_component_blends_last_night_and_debt(self) -> None:
        # last_night=8h -> 100; debt=5h -> 100-50=50. Blend -> 75.
        result = compute_readiness_score(last_night_sleep_hours=8.0, sleep_debt_hours=5.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(75.0)

    def test_sleep_component_from_last_night_only(self) -> None:
        result = compute_readiness_score(last_night_sleep_hours=4.0)  # half of need
        assert result["components"]["sleep"]["score"] == pytest.approx(50.0)

    def test_sleep_quality_blends_in_when_present(self) -> None:
        # Real gap found 2026-08-30: our duration+debt score read 97 the
        # same night Garmin's own quality-aware score read 74 "Fair" (low
        # REM) -- quantity alone missed that entirely. quantity here:
        # last_night=8h -> 100, debt=0h -> 100, quantity=100. Blended 50/50
        # with a real Garmin quality score of 74 -> (100+74)/2 = 87.
        result = compute_readiness_score(
            last_night_sleep_hours=8.0, sleep_debt_hours=0.0, sleep_quality_score=74.0
        )
        assert result["components"]["sleep"]["score"] == pytest.approx(87.0)

    def test_sleep_quality_missing_falls_back_to_quantity_only(self) -> None:
        # Exactly the pre-existing behavior when no Garmin sleep_score
        # exists for that date -- backward compatible, not a hard new
        # requirement.
        with_quality_none = compute_readiness_score(
            last_night_sleep_hours=8.0, sleep_debt_hours=0.0, sleep_quality_score=None
        )
        without_param = compute_readiness_score(last_night_sleep_hours=8.0, sleep_debt_hours=0.0)
        assert with_quality_none["components"]["sleep"]["score"] == pytest.approx(
            without_param["components"]["sleep"]["score"]
        )

    def test_sleep_raw_carries_quality_score_for_traceability(self) -> None:
        result = compute_readiness_score(
            last_night_sleep_hours=7.0, sleep_debt_hours=1.0, sleep_quality_score=80.0
        )
        assert result["components"]["sleep"]["raw"]["quality_score"] == 80.0

    def test_missing_components_renormalize_not_invented(self) -> None:
        # Only HRV (0.35) and subjective (0.10) present -> renormalized to
        # 0.35/0.45 and 0.10/0.45.
        result = compute_readiness_score(hrv_deviation_sd=2.0, hooper_index=4.0)
        assert result["coverage"] == pytest.approx(0.45)
        assert result["confidence"] == "partial"
        assert result["components"]["hrv"]["weight_used"] == pytest.approx(0.35 / 0.45)
        assert result["components"]["subjective"]["weight_used"] == pytest.approx(0.10 / 0.45)
        # Both components maxed out (100) -> renormalized score still 100.
        assert result["score"] == pytest.approx(100.0)

    def test_partial_coverage_hand_computed(self) -> None:
        # HRV score=100 (weight 0.35), RHR score=0 (weight 0.15).
        # coverage = 0.5, weighted = (100*0.35 + 0*0.15) / 0.5 = 70.0.
        result = compute_readiness_score(hrv_deviation_sd=2.0, rhr_deviation_sd=2.0)
        assert result["coverage"] == pytest.approx(0.5)
        assert result["score"] == pytest.approx(70.0)

    def test_custom_weights(self) -> None:
        result = compute_readiness_score(
            hrv_deviation_sd=2.0,
            rhr_deviation_sd=2.0,
            weights={"hrv": 0.9, "sleep": 0.0, "rhr": 0.1, "tsb": 0.0, "subjective": 0.0},
        )
        # hrv dominates: 100*0.9 + 0*0.1 = 90.
        assert result["score"] == pytest.approx(90.0)

    def test_score_always_between_0_and_100(self) -> None:
        result = compute_readiness_score(
            hrv_deviation_sd=-10.0,
            rhr_deviation_sd=10.0,
            last_night_sleep_hours=0.0,
            sleep_debt_hours=20.0,
            tsb_z_score=-10.0,
            hooper_index=40.0,
        )
        assert 0.0 <= result["score"] <= 100.0
