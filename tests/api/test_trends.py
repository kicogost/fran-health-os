from __future__ import annotations

import sqlite3

from health_os.api.trends import build_trends_payload
from health_os.core import db as db_module
from health_os.core.models import DailyMetric


def _write_derived(conn: sqlite3.Connection, date: str, value: float, confidence: str) -> None:
    db_module.upsert(
        conn,
        "derived_daily",
        {"date": date, "metric_name": "readiness_score", "value": value, "confidence": confidence},
        ["date", "metric_name"],
        touch_column="computed_at",
    )


class TestBuildTrendsPayload:
    def test_empty_db_returns_empty_series(self, conn: sqlite3.Connection) -> None:
        payload = build_trends_payload(conn, 90)
        assert payload == {
            "window_days": 90,
            "series": {},
            "sleep_stages": [],
            "readiness": {
                "label": "Readiness score",
                "raw": [],
                "smoothed": [],
                "coverage_summary": {},
            },
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
        payload = build_trends_payload(conn, 30)
        dates = [p["date"] for p in payload["series"]["weight_kg"]["raw"]]
        assert dates == ["2026-08-20", "2026-08-28"]

    def test_smoothed_series_present_alongside_raw(self, conn: sqlite3.Connection) -> None:
        for d, w in [("2026-08-26", 80.0), ("2026-08-27", 79.5), ("2026-08-28", 79.0)]:
            db_module.upsert(
                conn, "daily_metrics", DailyMetric(date=d, weight_kg=w).to_row(), ["date"]
            )
        payload = build_trends_payload(conn, 90)
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
        payload = build_trends_payload(conn, 90)
        assert len(payload["sleep_stages"]) == 1
        assert payload["sleep_stages"][0]["date"] == "2026-08-28"
        assert payload["sleep_stages"][0]["sleep_deep_min"] == 60


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

        payload = build_trends_payload(conn, 90)
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

        payload = build_trends_payload(conn, 90)
        assert payload["readiness"]["coverage_summary"] == {"partial": 2, "full": 1}

    def test_insufficient_data_rows_excluded_by_null_value(self, conn: sqlite3.Connection) -> None:
        # store_derived_metrics() always writes a row per metric per date --
        # even an insufficient_data one has value=NULL, and NULL isn't a
        # real readiness number to chart.
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-08-27", None, "insufficient_data")
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 90)
        assert [r["date"] for r in payload["readiness"]["raw"]] == ["2026-08-28"]

    def test_readiness_history_respects_the_window_cutoff(self, conn: sqlite3.Connection) -> None:
        self._seed_daily_metrics(conn, "2026-08-28")
        _write_derived(conn, "2026-01-01", 60.0, "full")  # well outside a 30-day window
        _write_derived(conn, "2026-08-28", 55.8, "full")

        payload = build_trends_payload(conn, 30)
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
        payload = build_trends_payload(conn, 90)
        assert payload["readiness"]["raw"] == []
