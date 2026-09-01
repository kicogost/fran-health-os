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
        # hrv/rhr at 0 deviation and hooper at its midpoint all score 50
        # (symmetric components) -- but sleep is NOT symmetric: hitting your
        # 7-9h band with zero debt is the sleep component's ceiling (100),
        # not a neutral midpoint. Hand-computed (ADR 0007 weights: hrv .35,
        # sleep .25, rhr .15, subjective .25 -- TSB removed entirely):
        # 0.35*50 + 0.25*100 + 0.15*50 + 0.25*50 = 62.5. (Coincidentally the
        # same total as the pre-ADR-0007 weights would have given here, since
        # every non-sleep component is at its own neutral midpoint -- removing
        # TSB's 0.15 and adding it to subjective doesn't change a sum where
        # both score 50.)
        result = compute_readiness_score(
            hrv_deviation_sd=0.0,
            rhr_deviation_sd=0.0,
            last_night_sleep_hours=8.0,
            sleep_debt_hours=0.0,
            hooper_index=22.0,  # midpoint of the 4-40 range
        )
        assert result["components"]["sleep"]["score"] == pytest.approx(100.0)
        assert result["score"] == pytest.approx(62.5)
        assert result["confidence"] == "full"
        assert result["coverage"] == pytest.approx(1.0)

    def test_hrv_component_direction_and_clamp(self) -> None:
        # +2 SD (clamped) HRV alone, nothing else -> full weight on hrv.
        # ADR 0007's noise floor still reaches the exact same 0/100
        # endpoints at the +-2 SD clamp boundary as ADR 0006's floor-less
        # quadratic did -- only the shape approaching 0 changed.
        result = compute_readiness_score(hrv_deviation_sd=5.0)  # clamped to +2
        assert result["components"]["hrv"]["score"] == pytest.approx(100.0)
        assert result["score"] == pytest.approx(100.0)
        assert result["components"]["hrv"]["weight_used"] == pytest.approx(1.0)

    def test_hrv_deviation_within_noise_floor_is_exactly_neutral(self) -> None:
        # ADR 0007's actual point: a deviation smaller than the +-0.2 SD
        # noise floor is treated as NO real signal at all, not just
        # dampened -- stays flat at 50, not nudged even slightly.
        result = compute_readiness_score(hrv_deviation_sd=0.15)
        assert result["components"]["hrv"]["score"] == pytest.approx(50.0)

    def test_hrv_at_one_sd_is_dampened_by_curve_and_floor(self) -> None:
        # A routine, statistically common ~1 SD deviation must NOT swing the
        # score a full quarter of the range (linear: 50+25=75) NOR even the
        # floor-less quadratic's 62.5 (ADR 0006 alone) -- ADR 0007 layers a
        # +-0.2 SD dead zone underneath the quadratic curve first. Hand-
        # computed: magnitude = 1.0 - 0.2 = 0.8, span = 2.0 - 0.2 = 1.8,
        # fraction = 0.8/1.8, score = 50 + 50*(0.8/1.8)**2 = 59.876543...
        result = compute_readiness_score(hrv_deviation_sd=1.0)
        assert result["components"]["hrv"]["score"] == pytest.approx(59.876543209876544)

    def test_rhr_component_is_inverted_vs_hrv(self) -> None:
        # Elevated RHR (positive deviation) should REDUCE readiness, opposite of HRV.
        result = compute_readiness_score(rhr_deviation_sd=2.0)
        assert result["components"]["rhr"]["score"] == pytest.approx(0.0)

    def test_rhr_at_one_sd_is_dampened_by_curve_and_floor(self) -> None:
        # Real motivating case (2026-08-30): a 2bpm RHR blip with no
        # sustained trend worked out to +1.04 SD. Under the ORIGINAL linear
        # mapping this scored 24/100 -- ADR 0006's quadratic alone brought
        # it to 37.5; ADR 0007's noise floor on top brings it further, to
        # 50 - 50*(0.8/1.8)**2 = 40.123456...
        result = compute_readiness_score(rhr_deviation_sd=1.0)
        assert result["components"]["rhr"]["score"] == pytest.approx(40.12345679012346)

    def test_real_2026_08_30_rhr_deviation_matches_hand_computed_value(self) -> None:
        # The exact real deviation that prompted ADR 0006 (52bpm vs. a
        # 50bpm/1.93bpm-SD baseline -> +1.0374553... SD). Hand-verified via
        # a standalone script before writing this assertion: magnitude =
        # 1.0374553608862056 - 0.2 = 0.8374553608862056, span = 1.8,
        # score = 50 - 50*(magnitude/span)**2 = 39.17698331053943 -- a real,
        # meaningful drop from neutral, but softer again than ADR 0006's
        # 36.546 (the noise floor eats the first 0.2 SD of the deviation
        # entirely, leaving less of it to drive the quadratic term).
        result = compute_readiness_score(rhr_deviation_sd=1.0374553608862056)
        assert result["components"]["rhr"]["score"] == pytest.approx(39.17698331053943, abs=0.001)

    def test_subjective_component_best_and_worst(self) -> None:
        best = compute_readiness_score(hooper_index=4.0)
        worst = compute_readiness_score(hooper_index=40.0)
        assert best["components"]["subjective"]["score"] == pytest.approx(100.0)
        assert worst["components"]["subjective"]["score"] == pytest.approx(0.0)

    def test_sleep_component_blends_last_night_and_debt(self) -> None:
        # 2026-08-31: debt can only ever act as a penalty, never a credit
        # (see _sleep_component_score's docstring) -- quantity is min(),
        # not an average. last_night=8h (>= the 7h band floor) -> 100;
        # debt=5h -> 100-50=50. min(100, 50) -> 50, not the old 75 average.
        result = compute_readiness_score(last_night_sleep_hours=8.0, sleep_debt_hours=5.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(50.0)

    def test_sleep_debt_credit_cannot_rescue_a_bad_night(self) -> None:
        # The exact real 2026-08-31 case that prompted this fix: a 5h50m
        # night (duration_score ~83) plus a real banked 14-day surplus
        # (debt_score ~100) must land at min(83, 100) = 83, NOT the ~91.65
        # a 50/50 average would have given. duration_score for 5h50m
        # (5.8333h) below the 7h band floor: 5.8333/7*100 = 83.3333...
        # debt=-2.0h (a 2h surplus) -> clamp(100 - (-2.0)*10, 0, 100) = 100.
        last_night_hours = 5.0 + 50.0 / 60.0
        expected_duration_score = last_night_hours / 7.0 * 100.0
        result = compute_readiness_score(
            last_night_sleep_hours=last_night_hours, sleep_debt_hours=-2.0
        )
        assert result["components"]["sleep"]["score"] == pytest.approx(expected_duration_score)
        # Explicitly NOT the old symmetric-average value.
        assert result["components"]["sleep"]["score"] != pytest.approx(91.65, abs=0.5)

    def test_sleep_debt_still_works_as_a_real_penalty(self) -> None:
        # Reverse case: a genuinely bad debt/surplus history (real chronic
        # deficit, debt=6h -> debt_score=40) alongside a perfectly fine last
        # night (8h -> duration_score=100) must still correctly drag the
        # score down to min(100, 40) = 40 -- debt is a real penalty signal,
        # not neutered by this change.
        result = compute_readiness_score(last_night_sleep_hours=8.0, sleep_debt_hours=6.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(40.0)

    def test_sleep_component_both_good_stays_good(self) -> None:
        result = compute_readiness_score(last_night_sleep_hours=8.0, sleep_debt_hours=-3.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(100.0)

    def test_sleep_component_both_bad_stays_bad(self) -> None:
        # last_night=3h -> 3/7*100 = 42.857...; debt=8h -> clamp(100-80,0,100)=20.
        # min -> 20.
        result = compute_readiness_score(last_night_sleep_hours=3.0, sleep_debt_hours=8.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(20.0)

    def test_sleep_component_within_band_scores_full_credit(self) -> None:
        # ADR 0007: any night in the 7-9h band scores 100 for quantity, not
        # just exactly-8h -- matches the NSF's own range-based consensus.
        result = compute_readiness_score(last_night_sleep_hours=7.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(100.0)

    def test_sleep_component_below_band_scales_from_the_band_floor(self) -> None:
        # ADR 0007: below the 7h band floor, quantity scales as
        # hours/7*100, not hours/8*100 -- 4h -> 4/7*100 = 57.142857...
        result = compute_readiness_score(last_night_sleep_hours=4.0)
        assert result["components"]["sleep"]["score"] == pytest.approx(57.14285714285714)

    def test_sleep_quality_blends_in_at_reduced_weight(self) -> None:
        # Real gap found 2026-08-30: our duration+debt score read 97 the
        # same night Garmin's own quality-aware score read 74 "Fair" (low
        # REM) -- quantity alone missed that entirely. ADR 0007 reduced the
        # blend from an even 50/50 to 25% quality (Garmin's own sleep-stage
        # classification is the least-validated signal in this project's
        # 2026-08-30 research review). quantity: last_night=8h -> 100,
        # debt=0h -> 100, quantity=100. Blended: 100*0.75 + 74*0.25 = 93.5.
        result = compute_readiness_score(
            last_night_sleep_hours=8.0, sleep_debt_hours=0.0, sleep_quality_score=74.0
        )
        assert result["components"]["sleep"]["score"] == pytest.approx(93.5)

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
        # Only HRV (0.35) and subjective (0.25, ADR 0007) present ->
        # renormalized to 0.35/0.60 and 0.25/0.60.
        result = compute_readiness_score(hrv_deviation_sd=2.0, hooper_index=4.0)
        assert result["coverage"] == pytest.approx(0.60)
        assert result["confidence"] == "partial"
        assert result["components"]["hrv"]["weight_used"] == pytest.approx(0.35 / 0.60)
        assert result["components"]["subjective"]["weight_used"] == pytest.approx(0.25 / 0.60)
        # Both components maxed out (100) -> renormalized score still 100.
        assert result["score"] == pytest.approx(100.0)

    def test_partial_coverage_hand_computed(self) -> None:
        # HRV score=100 (weight 0.35), RHR score=0 (weight 0.15) -- both
        # unchanged by ADR 0007 (only subjective's weight and TSB moved).
        # coverage = 0.5, weighted = (100*0.35 + 0*0.15) / 0.5 = 70.0.
        result = compute_readiness_score(hrv_deviation_sd=2.0, rhr_deviation_sd=2.0)
        assert result["coverage"] == pytest.approx(0.5)
        assert result["score"] == pytest.approx(70.0)

    def test_custom_weights(self) -> None:
        result = compute_readiness_score(
            hrv_deviation_sd=2.0,
            rhr_deviation_sd=2.0,
            weights={"hrv": 0.9, "sleep": 0.0, "rhr": 0.1, "subjective": 0.0},
        )
        # hrv dominates: 100*0.9 + 0*0.1 = 90.
        assert result["score"] == pytest.approx(90.0)

    def test_score_always_between_0_and_100(self) -> None:
        result = compute_readiness_score(
            hrv_deviation_sd=-10.0,
            rhr_deviation_sd=10.0,
            last_night_sleep_hours=0.0,
            sleep_debt_hours=20.0,
            hooper_index=40.0,
        )
        assert 0.0 <= result["score"] <= 100.0

    def test_tsb_no_longer_accepted(self) -> None:
        # ADR 0007: TSB removed from this composite entirely -- passing it
        # is a TypeError, not silently ignored, so a caller that forgets to
        # update finds out immediately rather than getting a quietly wrong
        # score.
        with pytest.raises(TypeError):
            compute_readiness_score(tsb_z_score=0.0)  # type: ignore[call-arg]
