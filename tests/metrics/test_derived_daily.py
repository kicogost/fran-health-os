"""Tests for metrics/derived_daily.py — the Phase 4 derived-metric
persistence layer (2026-08-28), the long-flagged gap where every computed
metric existed only as a live, on-demand call with no historical record.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import date, timedelta

from health_os.core import db as db_module
from health_os.core.models import BjjSession, DailyMetric, SubjectiveLogEntry
from health_os.metrics.baselines import DEFAULT_BASELINE_WINDOW_DAYS
from health_os.metrics.derived_daily import compute_derived_metrics, store_derived_metrics

_CONFIG = {
    "profile": {"age": 24},
    "training_load": {"bjj_rpe_calibration_factor": 1.0},
    "readiness_score": {
        "weight_hrv": 0.35,
        "weight_sleep": 0.25,
        "weight_rhr": 0.15,
        "weight_subjective": 0.25,
    },
    "goals": {"primary": {"date": "2026-10-18", "weight_division_kg": 77.0}},
}

_EXPECTED_METRIC_NAMES = {
    "hrv_baseline",
    "rhr_baseline",
    "sleep_debt",
    "ctl",
    "atl",
    "tsb",
    "monotony",
    "strain",
    "tsb_zscore",
    "weight_ewma",
    "weight_trend_slope",
    "comp_countdown_required_kg_per_week",
    "readiness_score",
}


def _date_range(end: date, n_days: int) -> list[date]:
    return [end - timedelta(days=i) for i in range(n_days - 1, -1, -1)]


class TestComputeDerivedMetricsShape:
    def test_every_known_metric_present_even_with_empty_db(self, conn: sqlite3.Connection) -> None:
        metrics = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        names = {m.metric_name for m in metrics}
        assert names == _EXPECTED_METRIC_NAMES
        assert all(m.confidence == "insufficient_data" for m in metrics)
        assert all(m.value is None for m in metrics)
        assert all(m.date == "2026-08-24" for m in metrics)

    def test_no_duplicate_metric_names(self, conn: sqlite3.Connection) -> None:
        metrics = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        names = [m.metric_name for m in metrics]
        assert len(names) == len(set(names))


class TestDateBounding:
    def test_hrv_baseline_does_not_leak_future_data(self, conn: sqlite3.Connection) -> None:
        # Same discipline as coach/briefing.py's fix -- every series here
        # must be bounded to <= as_of_date, never the whole table.
        as_of = date(2026, 8, 4)
        for d in _date_range(as_of, DEFAULT_BASELINE_WINDOW_DAYS):
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d.isoformat(), hrv_overnight_ms=90.0).to_row(),
                ["date"],
            )
        # Future days with wildly different HRV -- must not affect "today"'s read.
        for offset, hrv in enumerate([20.0, 15.0, 10.0], start=1):
            future = (as_of + timedelta(days=offset)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=future, hrv_overnight_ms=hrv).to_row(),
                ["date"],
            )

        result = compute_derived_metrics(conn, _CONFIG, as_of.isoformat())
        metrics = {m.metric_name: m for m in result}
        hrv = metrics["hrv_baseline"]
        assert hrv.confidence == "full"
        assert hrv.value == 0.0  # stable history, latest value == median -> deviation 0
        assert hrv.inputs["value_ms"] == 90.0  # NOT the future 20/15/10 values

    def test_load_metrics_do_not_leak_future_bjj_session(self, conn: sqlite3.Connection) -> None:
        as_of = "2026-07-10"
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-07-15", session_type="class", duration_min=90, session_rpe=9
            ).to_row(),
            ["date", "session_type"],
        )
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, as_of)}
        # No load data at all as of 2026-07-10 -- the future session must
        # not make these anything other than insufficient_data.
        assert metrics["ctl"].confidence == "insufficient_data"
        assert metrics["tsb"].value is None


class TestLoadSeriesNoLongerGoesStale:
    def test_a_gap_since_last_training_is_a_real_confirmed_rest_not_stale(
        self, conn: sqlite3.Connection
    ) -> None:
        # Rebuilt 2026-08-30: the OLD activities.training_load-based series
        # would have flagged this "stale" (a real bug this project used to
        # carry) -- the NEW activity-based series computes a genuine,
        # confirmed 0.0 for every day between the BJJ log and as_of_date,
        # so this is honestly "full" confidence, not "we don't know."
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-07-01", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        as_of = "2026-07-10"  # 9 days later, no training logged since
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, as_of)}
        assert metrics["ctl"].confidence == "full"
        assert metrics["ctl"].value is not None
        # CTL should have decayed some from the 42-day-tau EWMA over those
        # 9 real, confirmed rest days -- a genuinely smaller number than the
        # day training happened, not a carried-forward stale figure.
        as_of_bjj_day = {
            m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, "2026-07-01")
        }
        assert metrics["ctl"].value < as_of_bjj_day["ctl"].value

    def test_fresh_load_series_is_not_flagged_stale(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-07-10", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, "2026-07-10")}
        assert metrics["ctl"].confidence == "full"
        assert metrics["ctl"].inputs is None


class TestReadinessScoreMetric:
    def test_uses_hoopers_index_for_exact_as_of_date_only(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(
                date="2026-08-24", sleep_quality=2, stress=2, fatigue=2, muscle_soreness=2
            ).to_row(),
            ["date"],
        )
        # A DIFFERENT day's hooper_index must never leak into "today"'s score.
        db_module.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(
                date="2026-08-23", sleep_quality=9, stress=9, fatigue=9, muscle_soreness=9
            ).to_row(),
            ["date"],
        )
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, "2026-08-24")}
        readiness = metrics["readiness_score"]
        assert readiness.inputs["components"]["subjective"]["raw"] == 8  # 2+2+2+2, not 36

    def test_no_data_anywhere_gives_insufficient_data_score(self, conn: sqlite3.Connection) -> None:
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, "2026-08-24")}
        assert metrics["readiness_score"].confidence == "insufficient_data"
        assert metrics["readiness_score"].value is None

    def test_garmin_sleep_score_reaches_the_persisted_sleep_component(
        self, conn: sqlite3.Connection
    ) -> None:
        # Same real gap/fix as coach/briefing.py's identical wiring test --
        # this is the SEPARATE persistence-layer call site, kept in sync
        # deliberately (the earlier TSB-staleness fix taught this project
        # that these two call sites can silently drift apart otherwise).
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-24", sleep_total_min=449, sleep_score=74).to_row(),
            ["date"],
        )
        metrics = {m.metric_name: m for m in compute_derived_metrics(conn, _CONFIG, "2026-08-24")}
        readiness = metrics["readiness_score"]
        assert readiness.inputs["components"]["sleep"]["raw"]["quality_score"] == 74


class TestStoreDerivedMetrics:
    def test_computed_at_bumps_on_recompute(self, conn: sqlite3.Connection) -> None:
        # Real, previously-flagged gap: derived_daily.computed_at must
        # actually update on every recompute, not just get its DEFAULT on
        # first insert and then sit stale forever -- otherwise it would
        # misrepresent when a metric was last actually computed (design
        # principle 9).
        metrics = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        store_derived_metrics(conn, metrics)
        first = conn.execute(
            "SELECT computed_at FROM derived_daily WHERE date = ? AND metric_name = 'hrv_baseline'",
            ("2026-08-24",),
        ).fetchone()["computed_at"]

        time.sleep(0.01)
        store_derived_metrics(conn, metrics)
        second = conn.execute(
            "SELECT computed_at FROM derived_daily WHERE date = ? AND metric_name = 'hrv_baseline'",
            ("2026-08-24",),
        ).fetchone()["computed_at"]
        assert second > first

    def test_round_trip_and_upsert_on_natural_key(self, conn: sqlite3.Connection) -> None:
        metrics = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        written = store_derived_metrics(conn, metrics)
        assert written == len(metrics)

        rows = conn.execute(
            "SELECT * FROM derived_daily WHERE date = ?", ("2026-08-24",)
        ).fetchall()
        assert len(rows) == len(_EXPECTED_METRIC_NAMES)
        by_name = {r["metric_name"]: r for r in rows}
        assert by_name["hrv_baseline"]["confidence"] == "insufficient_data"

        # Re-storing (e.g. a recompute after new data arrived) must UPDATE,
        # not duplicate -- natural key is (date, metric_name).
        written_again = store_derived_metrics(conn, metrics)
        assert written_again == len(metrics)
        rows_after = conn.execute(
            "SELECT * FROM derived_daily WHERE date = ?", ("2026-08-24",)
        ).fetchall()
        assert len(rows_after) == len(_EXPECTED_METRIC_NAMES)

    def test_recompute_clears_a_stale_value_back_to_none(self, conn: sqlite3.Connection) -> None:
        # A metric that HAD a real value must actually clear to NULL if a
        # recompute genuinely finds insufficient data (e.g. after a data
        # correction removed some readings) -- store_derived_metrics() uses
        # include_none=True specifically so a full replace happens, not a
        # partial upsert that would leave a stale value under a new
        # confidence label.
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        first = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        store_derived_metrics(conn, first)
        row = conn.execute(
            "SELECT value FROM derived_daily WHERE date = ? AND metric_name = 'ctl'",
            ("2026-08-24",),
        ).fetchone()
        assert row["value"] is not None

        # Simulate the session being deleted (a correction) and recomputed.
        conn.execute("DELETE FROM bjj_sessions WHERE date = '2026-08-24'")
        second = compute_derived_metrics(conn, _CONFIG, "2026-08-24")
        store_derived_metrics(conn, second)
        row_after = conn.execute(
            "SELECT value, confidence FROM derived_daily WHERE date = ? AND metric_name = 'ctl'",
            ("2026-08-24",),
        ).fetchone()
        assert row_after["value"] is None
        assert row_after["confidence"] == "insufficient_data"
