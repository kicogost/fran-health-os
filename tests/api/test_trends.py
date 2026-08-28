from __future__ import annotations

import sqlite3

from health_os.api.trends import build_trends_payload
from health_os.core import db as db_module
from health_os.core.models import DailyMetric


class TestBuildTrendsPayload:
    def test_empty_db_returns_empty_series(self, conn: sqlite3.Connection) -> None:
        payload = build_trends_payload(conn, 90)
        assert payload == {"window_days": 90, "series": {}, "sleep_stages": []}

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
