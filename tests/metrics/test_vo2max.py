from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from health_os.metrics.vo2max import (
    HIDE_AFTER_WEEKS,
    SIGMA_ANCHOR_ML,
    bjj_rest_recovery,
    build_vo2max_summary,
    calibrate_personal_factor,
    estimate_on,
    rolling_rhr_median,
)

HR_MAX = 200.0
START = date(2026, 1, 1)


def _day(offset: int) -> str:
    return (START + timedelta(days=offset)).isoformat()


def _rhr(first: int, last: int, value: float) -> list[tuple[str, float]]:
    return [(_day(i), value) for i in range(first, last + 1)]


class TestRollingRhrMedian:
    def test_median_of_window(self) -> None:
        obs = _rhr(0, 13, 50.0) + _rhr(14, 27, 60.0)
        assert rolling_rhr_median(obs, _day(27)) == pytest.approx(55.0)

    def test_too_few_nights_is_none(self) -> None:
        assert rolling_rhr_median(_rhr(0, 12, 50.0), _day(27)) is None

    def test_window_excludes_older_days(self) -> None:
        # Days 0-27 at 70 fall outside the 28-day window ending on day 55.
        obs = _rhr(0, 27, 70.0) + _rhr(28, 55, 50.0)
        assert rolling_rhr_median(obs, _day(55)) == pytest.approx(50.0)


class TestCalibratePersonalFactor:
    def test_single_anchor_factor_and_fallback_sigma(self) -> None:
        # 50 = factor x 200/50  ->  factor = 12.5. One anchor has no spread to
        # measure, so sigma falls back to the anchor error, not zero.
        cal = calibrate_personal_factor([(_day(30), 50.0)], _rhr(0, 30, 50.0), HR_MAX)
        assert cal is not None
        assert cal["factor"] == pytest.approx(12.5)
        assert cal["sigma_cal"] == pytest.approx(SIGMA_ANCHOR_ML)
        assert cal["n_anchors"] == 1

    def test_two_anchors_mean_factor_and_residual_spread(self) -> None:
        # Factors 12.5 and 13.0 -> mean 12.75 -> both predict 51.0;
        # residuals -1 and +1 -> population SD 1.0.
        cal = calibrate_personal_factor(
            [(_day(30), 50.0), (_day(60), 52.0)], _rhr(0, 60, 50.0), HR_MAX
        )
        assert cal["factor"] == pytest.approx(12.75)
        assert cal["sigma_cal"] == pytest.approx(1.0)
        assert [a["predicted"] for a in cal["anchors"]] == pytest.approx([51.0, 51.0])

    def test_anchor_without_rhr_history_is_skipped(self) -> None:
        cal = calibrate_personal_factor(
            [(_day(5), 48.0), (_day(30), 50.0)], _rhr(10, 30, 50.0), HR_MAX
        )
        assert cal["n_anchors"] == 1

    def test_no_usable_anchor_is_none(self) -> None:
        assert calibrate_personal_factor([(_day(30), 50.0)], [], HR_MAX) is None


class TestEstimateOn:
    def _setup(self, rhr_after: float) -> tuple[list, list, dict]:
        vo2 = [(_day(30), 50.0), (_day(60), 52.0)]
        rhr = _rhr(0, 60, 50.0) + _rhr(61, 400, rhr_after)
        return vo2, rhr, calibrate_personal_factor(vo2, rhr, HR_MAX)

    def test_measured_date(self) -> None:
        vo2, rhr, cal = self._setup(50.0)
        point = estimate_on(_day(60), vo2, rhr, HR_MAX, cal)
        assert point["status"] == "measured"
        assert point["value"] == 52.0

    def test_estimate_value_and_sigma(self) -> None:
        # 70 days after the last anchor = 10 weeks. RHR steady at 50 ->
        # 12.75 x 200/50 = 51.0. sigma = sqrt(3.5^2 + 1.0^2 + (0.3 x 10)^2)
        vo2, rhr, cal = self._setup(50.0)
        point = estimate_on(_day(130), vo2, rhr, HR_MAX, cal)
        assert point["status"] == "estimate"
        assert point["value"] == pytest.approx(51.0)
        expected_sigma = math.sqrt(3.5**2 + 1.0**2 + 3.0**2)
        assert point["sigma"] == pytest.approx(round(expected_sigma, 1))
        assert point["low"] == pytest.approx(round(51.0 - expected_sigma, 1))
        assert point["clamped"] is False

    def test_large_rhr_drop_is_capped_near_anchor(self) -> None:
        # RHR 40 -> raw 63.75, capped at 52 x 1.10 = 57.2.
        vo2, rhr, cal = self._setup(40.0)
        point = estimate_on(_day(130), vo2, rhr, HR_MAX, cal)
        assert point["value"] == pytest.approx(57.2)
        assert point["clamped"] is True

    def test_large_rhr_rise_is_floored(self) -> None:
        # RHR 70 -> raw 36.4, floored at 52 x 0.84 = 43.68.
        vo2, rhr, cal = self._setup(70.0)
        point = estimate_on(_day(130), vo2, rhr, HR_MAX, cal)
        assert point["value"] == pytest.approx(43.7)

    def test_low_confidence_after_12_weeks(self) -> None:
        vo2, rhr, cal = self._setup(50.0)
        assert estimate_on(_day(60 + 13 * 7), vo2, rhr, HR_MAX, cal)["status"] == "low_confidence"

    def test_hidden_after_26_weeks(self) -> None:
        vo2, rhr, cal = self._setup(50.0)
        point = estimate_on(_day(60 + (HIDE_AFTER_WEEKS + 1) * 7), vo2, rhr, HR_MAX, cal)
        assert point["status"] == "too_old"
        assert point["value"] is None

    def test_before_any_measurement(self) -> None:
        vo2, rhr, cal = self._setup(50.0)
        assert estimate_on(_day(10), vo2, rhr, HR_MAX, cal)["status"] == "insufficient_data"

    def test_no_recent_rhr_is_insufficient(self) -> None:
        vo2 = [(_day(30), 50.0)]
        rhr = _rhr(0, 30, 50.0)
        cal = calibrate_personal_factor(vo2, rhr, HR_MAX)
        point = estimate_on(_day(100), vo2, rhr, HR_MAX, cal)
        assert point["status"] == "insufficient_data"
        assert point["value"] is None


def _seg(label: str, start: float, end: float, hr: float | None) -> dict:
    return {"label": label, "start_s": start, "end_s": end, "avg_hr": hr}


class TestBjjRestRecovery:
    def test_mean_round_to_rest_drop(self) -> None:
        segments = [
            _seg("warmup_or_drilling", 0, 600, 120),
            _seg("round", 600, 900, 185),
            _seg("rest", 900, 960, 165),
            _seg("round", 960, 1260, 180),
            _seg("rest", 1260, 1320, 170),
        ]
        assert bjj_rest_recovery(segments) == pytest.approx(15.0)

    def test_truncated_final_rest_excluded(self) -> None:
        segments = [
            _seg("round", 0, 300, 185),
            _seg("rest", 300, 360, 165),
            _seg("round", 360, 660, 180),
            _seg("rest", 660, 690, 178),  # 30s tail, watch stopped
        ]
        assert bjj_rest_recovery(segments) == pytest.approx(20.0)

    def test_no_pairs_is_none(self) -> None:
        assert bjj_rest_recovery([_seg("warmup_or_drilling", 0, 600, 120)]) is None


class TestBuildVo2maxSummary:
    def _inputs(self) -> dict:
        return {
            "vo2_obs": [(_day(30), 50.0), (_day(60), 52.0), (_day(500), 99.0)],
            "rhr_obs": _rhr(0, 130, 50.0),
            "hrv_obs": _rhr(0, 130, 90.0),
            "weight_ewma": [(_day(60), 80.0), (_day(130), 76.0)],
            "hr_max": HR_MAX,
            "as_of": _day(130),
        }

    def test_future_measurement_never_leaks(self) -> None:
        summary = build_vo2max_summary(**self._inputs())
        assert summary["latest_measurement"]["value"] == 52.0
        assert [m["value"] for m in summary["measurements"]] == [50.0, 52.0]

    def test_weight_only_effect(self) -> None:
        # 52 x 80/76 = 54.7 -- the ml/kg/min gain from weight loss alone.
        summary = build_vo2max_summary(**self._inputs())
        assert summary["weight_only"]["value"] == pytest.approx(54.7)

    def test_estimate_series_ends_on_as_of(self) -> None:
        summary = build_vo2max_summary(**self._inputs())
        assert summary["estimate_series"][-1]["date"] == _day(130)
        assert all(
            p["status"] in ("estimate", "low_confidence") for p in summary["estimate_series"]
        )

    def test_estimate_series_starts_after_last_measurement(self) -> None:
        summary = build_vo2max_summary(**self._inputs())
        assert all(p["date"] > _day(60) for p in summary["estimate_series"])

    def test_maintained_caveat_only_when_estimate_above_anchor(self) -> None:
        flat = build_vo2max_summary(**self._inputs())
        assert "maintained" not in flat["meaning"]["headline"]

        inputs = self._inputs()
        inputs["rhr_obs"] = _rhr(0, 60, 50.0) + _rhr(61, 130, 45.0)
        lower_rhr = build_vo2max_summary(**inputs)
        assert lower_rhr["current"]["value"] > 52.0
        assert "maintained" in lower_rhr["meaning"]["headline"]

    def test_no_measurements_at_all(self) -> None:
        inputs = self._inputs()
        inputs["vo2_obs"] = []
        summary = build_vo2max_summary(**inputs)
        assert summary["latest_measurement"] is None
        assert summary["current"]["status"] == "insufficient_data"
        assert summary["meaning"]["tone"] == "unknown"
