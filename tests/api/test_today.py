"""Tests for api/today.py — the pure assembly function behind the FastAPI
/api/today route (ADR 0005 frontend migration).
"""

from __future__ import annotations

import sqlite3

from health_os.api.today import build_today_payload
from health_os.core import db as db_module
from health_os.core.models import DailyMetric

_CONFIG = {
    "comp_prep": {
        "weekly_template": [
            {"day": "monday", "sessions": [{"type": "bjj", "subtype": "no_gi_technical"}]},
        ]
    },
    "training_load": {"bjj_rpe_calibration_factor": 1.0},
    "readiness_score": {
        "weight_hrv": 0.35,
        "weight_sleep": 0.25,
        "weight_rhr": 0.15,
        "weight_tsb": 0.15,
        "weight_subjective": 0.10,
    },
    "nutrition": {"protein_g_daily_min": 180},
    "goals": {"primary": {"date": "2026-10-18", "weight_division_kg": 77.0}},
}


class TestBuildTodayPayload:
    def test_basic_shape_with_no_data(self, conn: sqlite3.Connection) -> None:
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert payload["date"] == "2026-08-24"
        assert payload["weekday_name"] == "monday"
        assert payload["readiness"]["band"] == "no_data"
        assert payload["sleep"] is None
        assert payload["weight"] is None
        assert payload["comp_countdown"] is None
        assert len(payload["sessions"]) == 1

    def test_sleep_included_when_present(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(
                date="2026-08-24",
                sleep_total_min=480,
                sleep_deep_min=60,
                sleep_light_min=300,
                sleep_rem_min=100,
                sleep_awake_min=20,
            ).to_row(),
            ["date"],
        )
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert payload["sleep"] == {
            "total_min": 480,
            "deep_min": 60,
            "light_min": 300,
            "rem_min": 100,
            "awake_min": 20,
        }

    def test_weight_and_comp_countdown_included_when_present(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-24", weight_kg=79.0).to_row(), ["date"]
        )
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert payload["weight"]["latest_kg"] == 79.0
        assert payload["weight"]["latest_date"] == "2026-08-24"
        assert payload["comp_countdown"]["kg_remaining"] == 2.0

    def test_weight_after_today_is_not_leaked_in(self, conn: sqlite3.Connection) -> None:
        # Same date-bounding discipline as everywhere else in this project
        # (coach/briefing.py, metrics/derived_daily.py) -- a weigh-in logged
        # AFTER the requested date must not affect that date's payload.
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-25", weight_kg=999.0).to_row(),
            ["date"],
        )
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert payload["weight"] is None

    def test_readiness_components_are_json_serializable_shape(
        self, conn: sqlite3.Connection
    ) -> None:
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert isinstance(payload["readiness"]["components"], dict)
        assert isinstance(payload["structural_flags"], dict)
