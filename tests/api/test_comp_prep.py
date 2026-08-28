from __future__ import annotations

import sqlite3

from health_os.api.comp_prep import build_comp_prep_payload
from health_os.core import db as db_module
from health_os.core.models import DailyMetric

_CONFIG = {
    "goals": {"primary": {"name": "No-gi comp", "date": "2026-10-18", "weight_division_kg": 77.0}}
}


class TestBuildCompPrepPayload:
    def test_no_weight_data(self, conn: sqlite3.Connection) -> None:
        payload = build_comp_prep_payload(conn, _CONFIG)
        assert payload["has_weight_data"] is False
        assert payload["goal"]["weight_limit_kg"] == 77.0

    def test_with_weight_data_computes_countdown(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=79.0).to_row(), ["date"]
        )
        payload = build_comp_prep_payload(conn, _CONFIG)
        assert payload["has_weight_data"] is True
        assert payload["countdown"]["kg_remaining"] == 2.0
        assert len(payload["weight_raw"]) == 1
        assert len(payload["required_path"]) >= 1
        # First point of the required path starts at the current weight.
        assert payload["required_path"][0]["value"] == payload["countdown"]["current_weight_kg"]
        # Last point of the required path lands exactly on the division limit.
        assert payload["required_path"][-1]["value"] == 77.0

    def test_insufficient_trend_data_has_no_projection(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", DailyMetric(date="2026-08-28", weight_kg=79.0).to_row(), ["date"]
        )
        payload = build_comp_prep_payload(conn, _CONFIG)
        assert payload["trend"]["confidence"] == "insufficient_data"
        assert payload["projection"] is None
