from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta

from health_os.api.data_health import build_data_health_payload
from health_os.core import db as db_module
from health_os.core.models import Activity, DailyMetric
from health_os.core.timezones import to_local_date


class TestBuildDataHealthPayload:
    def test_no_data_anywhere(self, conn: sqlite3.Connection) -> None:
        payload = build_data_health_payload(conn)
        assert all(f["status"] == "no_data" for f in payload["freshness"])
        assert payload["missing_days"] == []
        assert payload["dedupe_log"] == []
        assert payload["ingest_runs"] == []

    def test_freshness_reports_today_for_the_latest_row(self, conn: sqlite3.Connection) -> None:
        today = to_local_date(datetime.now(UTC))
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date=today, weight_kg=79.0).to_row(), ["date"]
        )
        payload = build_data_health_payload(conn)
        weight_field = next(f for f in payload["freshness"] if f["field"] == "weight_kg")
        assert weight_field["status"] == "today"
        assert weight_field["days_stale"] == 0

    def test_freshness_reports_days_stale_for_an_older_row(self, conn: sqlite3.Connection) -> None:
        today = datetime.now(UTC).date()
        stale_date = (today - timedelta(days=5)).isoformat()
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date=stale_date, resting_hr=50.0).to_row(),
            ["date"],
        )
        payload = build_data_health_payload(conn)
        rhr_field = next(f for f in payload["freshness"] if f["field"] == "resting_hr")
        assert rhr_field["days_stale"] == 5
        assert rhr_field["status"] == "5d ago"

    def test_missing_days_detects_a_real_gap(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-01", weight_kg=80.0).to_row(), ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-05", weight_kg=79.5).to_row(), ["date"]
        )
        payload = build_data_health_payload(conn)
        # Window is the trailing 30 days ending on the max date (2026-08-05).
        assert "2026-08-03" in payload["missing_days"]
        assert "2026-08-01" not in payload["missing_days"]
        assert "2026-08-05" not in payload["missing_days"]

    def test_dedupe_log_only_includes_rows_with_real_merges(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "activities",
            Activity(
                activity_id="garmin:1",
                source="garmin",
                source_id="1",
                start_utc="2026-08-24T10:00:00Z",
                local_date="2026-08-24",
                merged_from=[{"source": "strava", "source_id": "99"}],
            ).to_row(),
            ["source", "source_id"],
        )
        db_module.upsert(
            conn,
            "activities",
            Activity(
                activity_id="garmin:2",
                source="garmin",
                source_id="2",
                start_utc="2026-08-25T10:00:00Z",
                local_date="2026-08-25",
            ).to_row(),
            ["source", "source_id"],
        )
        payload = build_data_health_payload(conn)
        assert len(payload["dedupe_log"]) == 1
        assert payload["dedupe_log"][0]["activity_id"] == "garmin:1"
        assert payload["dedupe_log"][0]["merged_from"] == [{"source": "strava", "source_id": "99"}]

    def test_ingest_runs_returned_most_recent_first(self, conn: sqlite3.Connection) -> None:
        run1 = db_module.start_ingest_run(conn, "garmin")
        db_module.finish_ingest_run(conn, run1, status="success", rows_upserted=3)
        time.sleep(0.01)
        run2 = db_module.start_ingest_run(conn, "strava")
        db_module.finish_ingest_run(conn, run2, status="failed", errors=["boom"])
        payload = build_data_health_payload(conn)
        assert len(payload["ingest_runs"]) == 2
        assert payload["ingest_runs"][0]["source"] == "strava"
        assert payload["ingest_runs"][0]["errors"] == ["boom"]
