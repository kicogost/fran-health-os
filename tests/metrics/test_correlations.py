from __future__ import annotations

import sqlite3

import pytest

from health_os.core import db as db_module
from health_os.metrics.correlations import (
    MIN_N,
    CorrelationResult,
    build_daily_metrics_correlation_panel,
    compute_correlation,
    compute_correlation_panel,
    correlation_result_to_dict,
)


class TestComputeCorrelation:
    def test_insufficient_data_below_min_n(self) -> None:
        x = [1.0, 2.0, 3.0]
        y = [1.0, 2.0, 3.0]
        result = compute_correlation(x, y, "x", "y")
        assert result.confidence == "insufficient_data"
        assert result.n == 3
        assert result.rho is None
        assert result.p_value is None

    def test_perfect_monotonic_increasing_gives_rho_exactly_one(self) -> None:
        # A hand-verifiable exact value, not an approximation: when y is a
        # strictly increasing function of x, every rank matches exactly, so
        # Spearman's rho is exactly 1.0 regardless of the actual magnitudes.
        x = list(range(MIN_N))
        y = [v * 2.5 + 3 for v in x]
        result = compute_correlation(x, y, "x", "y")
        assert result.n == MIN_N
        assert result.rho == pytest.approx(1.0)
        assert result.confidence == "significant"

    def test_perfect_monotonic_decreasing_gives_rho_exactly_negative_one(self) -> None:
        x = list(range(MIN_N))
        y = [-v for v in x]
        result = compute_correlation(x, y, "x", "y")
        assert result.rho == pytest.approx(-1.0)
        assert result.confidence == "significant"

    def test_pairwise_drops_none_on_either_side(self) -> None:
        # 30 real pairs plus 5 where one side is None -- the Nones must be
        # dropped, not coerced into zero or crashing the comparison.
        x = list(range(MIN_N)) + [None, 1, None, 2, None]
        y = [v * 2.0 for v in range(MIN_N)] + [1, None, 2, None, 3]
        result = compute_correlation(x, y, "x", "y")
        assert result.n == MIN_N  # only the fully-aligned pairs count
        assert result.rho == pytest.approx(1.0)

    def test_no_real_relationship_is_not_significant(self) -> None:
        # A constant y has zero rank variance -- no real relationship to
        # detect, and definitely shouldn't report "significant".
        x = list(range(MIN_N))
        y = [5.0] * MIN_N
        result = compute_correlation(x, y, "x", "y")
        assert result.confidence in {"not_significant", "insufficient_data"}
        assert result.confidence != "significant"

    def test_mismatched_lengths_raises(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            compute_correlation([1.0, 2.0], [1.0], "x", "y")

    def test_description_carried_through(self) -> None:
        x = list(range(MIN_N))
        y = list(range(MIN_N))
        result = compute_correlation(x, y, "x", "y", description="test pair")
        assert result.description == "test pair"


class TestComputeCorrelationPanel:
    def test_bonferroni_correction_uses_only_tested_pair_count(self) -> None:
        # Pair A has plenty of data (n = MIN_N); pair B does not (n = 3).
        # Only A was actually "tested" in the multiple-comparisons sense, so
        # A's corrected alpha must be 0.05 / 1, not 0.05 / 2.
        series = {
            "a_x": list(range(MIN_N)),
            "a_y": list(range(MIN_N)),
            "b_x": [1.0, 2.0, 3.0],
            "b_y": [1.0, 2.0, 3.0],
        }
        pairs = [("a_x", "a_y", "pair a"), ("b_x", "b_y", "pair b")]
        results = compute_correlation_panel(series, pairs)
        by_name = {r.description: r for r in results}
        assert by_name["pair a"].alpha_used == pytest.approx(0.05)
        assert by_name["pair b"].confidence == "insufficient_data"
        assert by_name["pair b"].alpha_used is None

    def test_correction_can_flip_a_borderline_pair_to_not_significant(self) -> None:
        # Constructs a real borderline case rather than asserting the
        # mechanism abstractly: pair A is a strong, clearly-significant
        # relationship; pair B is a weak, noisy one whose UNCORRECTED
        # p-value clears the standard 0.05 bar but should NOT survive
        # dividing by 2 (Bonferroni across 2 tested pairs).
        import random

        # Two independent RNGs (not one shared stream) so each series' draw
        # sequence -- and therefore this test's determinism -- doesn't
        # depend on which pair happens to be built first.
        n = MIN_N
        a_rng = random.Random(1)
        a_x = list(range(n))
        a_y = [v + a_rng.uniform(-0.1, 0.1) for v in a_x]  # near-perfect monotonic

        b_rng = random.Random(42)
        b_x = list(range(n))
        b_y = [v + b_rng.uniform(-45, 45) for v in b_x]  # noisy, weak relationship

        # Sanity check the fixture actually produces the borderline shape
        # this test needs (verified once via a throwaway script: seed 42 +
        # amplitude 45 lands at p~0.04, reliably inside 0.01-0.05), rather
        # than trusting the noise generator blindly forever.
        weak_uncorrected = compute_correlation(b_x, b_y, "b_x", "b_y")
        assert weak_uncorrected.p_value is not None
        assert 0.01 < weak_uncorrected.p_value < 0.05, (
            f"fixture drifted out of the intended borderline range: p={weak_uncorrected.p_value}"
        )

        series = {"a_x": a_x, "a_y": a_y, "b_x": b_x, "b_y": b_y}
        pairs = [("a_x", "a_y", "strong"), ("b_x", "b_y", "weak")]
        results = compute_correlation_panel(series, pairs)
        by_desc = {r.description: r for r in results}
        assert by_desc["strong"].confidence == "significant"
        assert by_desc["weak"].confidence == "not_significant"

    def test_no_pairs_tested_returns_all_insufficient_unchanged(self) -> None:
        series = {"x": [1.0, 2.0], "y": [1.0, 2.0]}
        results = compute_correlation_panel(series, [("x", "y", "too little data")])
        assert results[0].confidence == "insufficient_data"
        assert results[0].alpha_used is None


class TestCorrelationResultToDict:
    def test_shape(self) -> None:
        result = CorrelationResult("x", "y", 30, 0.8, 0.001, 0.05, "significant", "desc")
        d = correlation_result_to_dict(result)
        assert d == {
            "x_name": "x",
            "y_name": "y",
            "description": "desc",
            "n": 30,
            "rho": 0.8,
            "p_value": 0.001,
            "alpha_used": 0.05,
            "confidence": "significant",
        }


class TestBuildDailyMetricsCorrelationPanel:
    def test_sparse_real_data_reports_insufficient_data(self, conn: sqlite3.Connection) -> None:
        # Mirrors the actual current state of the real database (2026-08-30):
        # one subjective_log row -- every pair involving it must honestly
        # report insufficient_data, not a fabricated correlation.
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-28", "hrv_overnight_ms": 88.0, "resting_hr": 49.0},
            ["date"],
        )
        db_module.upsert(
            conn,
            "subjective_log",
            {"date": "2026-08-28", "sleep_quality": 2, "stress": 7, "hooper_index": 18},
            ["date"],
        )
        results = build_daily_metrics_correlation_panel(conn)
        assert all(r.confidence == "insufficient_data" for r in results)

    def test_enough_synthetic_data_yields_a_real_computed_pair(
        self, conn: sqlite3.Connection
    ) -> None:
        for i in range(MIN_N):
            d = f"2026-01-{i + 1:02d}" if i < 31 else f"2026-02-{i - 30:02d}"
            db_module.upsert(
                conn, "daily_metrics", {"date": d, "hrv_overnight_ms": 70.0 + i}, ["date"]
            )
            db_module.upsert(
                conn, "subjective_log", {"date": d, "sleep_quality": 1 + (i % 10)}, ["date"]
            )
        results = build_daily_metrics_correlation_panel(conn)
        by_x = {r.x_name: r for r in results}
        assert by_x["sleep_quality"].n == MIN_N
        assert by_x["sleep_quality"].confidence != "insufficient_data"
