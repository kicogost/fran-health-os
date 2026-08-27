from __future__ import annotations

import statistics
from math import exp

import pytest

from health_os.metrics.load import (
    build_daily_load_series,
    compute_acwr,
    compute_ctl_atl,
    compute_monotony_strain,
)


class TestBuildDailyLoadSeries:
    def test_fills_gap_days_with_zero(self) -> None:
        series = build_daily_load_series(
            activity_loads=[("2026-08-01", 100.0), ("2026-08-03", 50.0)],
            bjj_loads=[],
        )
        assert series == [
            ("2026-08-01", 100.0),
            ("2026-08-02", 0.0),
            ("2026-08-03", 50.0),
        ]

    def test_activity_and_bjj_load_summed_on_same_day(self) -> None:
        series = build_daily_load_series(
            activity_loads=[("2026-08-01", 100.0)],
            bjj_loads=[("2026-08-01", 630.0)],
        )
        assert series == [("2026-08-01", 730.0)]

    def test_calibration_factor_applies_only_to_bjj(self) -> None:
        series = build_daily_load_series(
            activity_loads=[("2026-08-01", 100.0)],
            bjj_loads=[("2026-08-01", 630.0)],
            bjj_calibration_factor=0.5,
        )
        assert series == [("2026-08-01", 100.0 + 315.0)]

    def test_empty_input(self) -> None:
        assert build_daily_load_series([], []) == []


class TestComputeAcwr:
    def test_insufficient_data_below_35_days(self) -> None:
        loads = [(f"2026-01-{d:02d}", 100.0) for d in range(1, 20)]
        result = compute_acwr(loads)
        assert result["confidence"] == "insufficient_data"
        assert result["acwr"] is None

    def test_constant_load_gives_acwr_one_sweet_spot(self) -> None:
        # 35 days, all load=100: acute=700, every 7-day-sum=700, chronic=700, acwr=1.0.
        loads = [(f"2026-01-{d:02d}", 100.0) for d in range(1, 36)]
        result = compute_acwr(loads)
        assert result["confidence"] == "full"
        assert result["acute_load"] == pytest.approx(700.0)
        assert result["chronic_load"] == pytest.approx(700.0)
        assert result["acwr"] == pytest.approx(1.0)
        assert result["flag"] == "sweet_spot"

    def test_ramping_too_fast_hand_computed(self) -> None:
        # 28 days @ 50/day, then 7 days @ 200/day. Hand-computed:
        # acute = 200*7 = 1400. chronic = 14000/28 = 500. acwr = 1400/500 = 2.8.
        loads = [(f"d{i}", 50.0) for i in range(28)] + [(f"d{i}", 200.0) for i in range(28, 35)]
        result = compute_acwr(loads)
        assert result["acute_load"] == pytest.approx(1400.0)
        assert result["chronic_load"] == pytest.approx(500.0)
        assert result["acwr"] == pytest.approx(2.8)
        assert result["flag"] == "ramping_too_fast"

    def test_detraining_hand_computed(self) -> None:
        # 28 days @ 200/day, then 7 days @ 20/day. Hand-computed:
        # acute = 20*7 = 140. chronic = 34160/28 = 1220. acwr = 140/1220 ~ 0.1148.
        loads = [(f"d{i}", 200.0) for i in range(28)] + [(f"d{i}", 20.0) for i in range(28, 35)]
        result = compute_acwr(loads)
        assert result["acute_load"] == pytest.approx(140.0)
        assert result["chronic_load"] == pytest.approx(1220.0)
        assert result["acwr"] == pytest.approx(140 / 1220)
        assert result["flag"] == "detraining"


class TestComputeMonotonyStrain:
    def test_insufficient_data_below_window(self) -> None:
        loads = [(f"d{i}", 100.0) for i in range(5)]
        result = compute_monotony_strain(loads, window_days=7)
        assert result["confidence"] == "insufficient_data"

    def test_zero_variance_is_undefined_not_a_sentinel(self) -> None:
        loads = [(f"d{i}", 100.0) for i in range(7)]
        result = compute_monotony_strain(loads)
        assert result["monotony"] is None
        assert result["confidence"] == "undefined_zero_variance"
        assert result["weekly_load"] == pytest.approx(700.0)

    def test_hand_computed_against_stdlib_formula(self) -> None:
        loads_only = [90.0, 110.0, 100.0, 80.0, 120.0, 95.0, 105.0]
        daily_loads = [(f"2026-08-{i + 1:02d}", v) for i, v in enumerate(loads_only)]
        result = compute_monotony_strain(daily_loads)

        mean = statistics.mean(loads_only)
        sd = statistics.pstdev(loads_only)
        expected_monotony = mean / sd
        expected_weekly = sum(loads_only)
        expected_strain = expected_weekly * expected_monotony

        assert result["monotony"] == pytest.approx(expected_monotony)
        assert result["weekly_load"] == pytest.approx(expected_weekly)
        assert result["strain"] == pytest.approx(expected_strain)
        # mean=100, pstdev~12.2 -> monotony~8.2: high, because +-20 around a mean of
        # 100 isn't much day-to-day contrast. Foster's formula runs high whenever
        # variation is small *relative to* the mean, not just in absolute terms.
        assert result["flag_high_monotony"] is True

    def test_high_monotony_flagged(self) -> None:
        # Low variance relative to mean -> monotony well above 2.0.
        loads_only = [100.0, 101.0, 99.0, 100.0, 101.0, 99.0, 100.0]
        daily_loads = [(f"2026-08-{i + 1:02d}", v) for i, v in enumerate(loads_only)]
        result = compute_monotony_strain(daily_loads)
        assert result["monotony"] > 2.0
        assert result["flag_high_monotony"] is True

    def test_only_uses_trailing_window(self) -> None:
        # 14 days: first 7 wildly different (would change mean/SD a lot), last 7
        # constant-ish. Only the last 7 should be used.
        loads = [(f"a{i}", 10.0 * i) for i in range(7)] + [(f"b{i}", 100.0) for i in range(7)]
        result = compute_monotony_strain(loads)
        assert result["confidence"] == "undefined_zero_variance"  # last 7 are all 100


class TestComputeCtlAtl:
    def test_empty_input(self) -> None:
        assert compute_ctl_atl([]) == []

    def test_single_day_seeds_both_at_load(self) -> None:
        result = compute_ctl_atl([("2026-08-01", 500.0)])
        assert result == [("2026-08-01", 500.0, 500.0, 0.0)]

    def test_constant_load_stays_constant(self) -> None:
        loads = [(f"d{i}", 200.0) for i in range(10)]
        result = compute_ctl_atl(loads)
        for _, ctl, atl, tsb in result:
            assert ctl == pytest.approx(200.0)
            assert atl == pytest.approx(200.0)
            assert tsb == pytest.approx(0.0)

    def test_atl_responds_faster_than_ctl_to_a_spike(self) -> None:
        # 10 rest days (both series settle at 0), then one big spike day.
        loads = [(f"rest{i}", 0.0) for i in range(10)] + [("spike", 700.0)]
        result = compute_ctl_atl(loads)
        _, ctl_spike, atl_spike, tsb_spike = result[-1]
        # ATL (short time constant) must move further toward the spike than CTL.
        assert atl_spike > ctl_spike
        # TSB (freshness) drops sharply on a big one-off session.
        assert tsb_spike < 0

    def test_hand_computed_single_step_from_zero_baseline(self) -> None:
        # Independently re-derive the exact single-step formula (not importing
        # the module's internals) to catch transcription bugs, not just
        # structural ones.
        ctl_alpha = 1 - exp(-1 / 42.0)
        atl_alpha = 1 - exp(-1 / 7.0)
        loads = [(f"rest{i}", 0.0) for i in range(5)] + [("spike", 700.0)]
        result = compute_ctl_atl(loads)
        _, ctl_spike, atl_spike, tsb_spike = result[-1]
        assert ctl_spike == pytest.approx(700.0 * ctl_alpha)
        assert atl_spike == pytest.approx(700.0 * atl_alpha)
        assert tsb_spike == pytest.approx(700.0 * ctl_alpha - 700.0 * atl_alpha)

    def test_custom_tau_values(self) -> None:
        result = compute_ctl_atl([("d0", 0.0), ("d1", 100.0)], ctl_tau_days=1.0, atl_tau_days=1.0)
        # With identical tau, CTL and ATL must move identically -> TSB stays 0.
        for _, ctl, atl, tsb in result:
            assert ctl == pytest.approx(atl)
            assert tsb == pytest.approx(0.0)
