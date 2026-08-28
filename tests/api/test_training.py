from __future__ import annotations

import sqlite3

from health_os.api.training import build_training_payload
from health_os.core import db as db_module
from health_os.core.models import Activity, BjjSession, CalisthenicsSession

_CONFIG = {"training_load": {"bjj_rpe_calibration_factor": 1.0}}


class TestBuildTrainingPayload:
    def test_no_load_data_reports_has_load_data_false(self, conn: sqlite3.Connection) -> None:
        payload = build_training_payload(conn, _CONFIG)
        assert payload["has_load_data"] is False
        assert payload["ctl_atl_tsb"] == []
        assert payload["tsb_zscore"] is None
        assert payload["monotony_strain"] is None

    def test_bjj_load_populates_ctl_atl_tsb(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG)
        assert payload["has_load_data"] is True
        assert len(payload["ctl_atl_tsb"]) == 1
        assert payload["ctl_atl_tsb"][0]["date"] == "2026-08-24"

    def test_load_by_sport_fills_null_sport_as_unknown(self, conn: sqlite3.Connection) -> None:
        # Real gap this session already found and fixed on the Streamlit
        # side (training.py): pandas groupby(dropna=True) silently drops
        # NULL-sport activities. This SQL-level COALESCE must not repeat it.
        db_module.upsert(
            conn,
            "activities",
            Activity(
                activity_id="garmin:1",
                source="garmin",
                source_id="1",
                start_utc="2026-08-24T10:00:00Z",
                local_date="2026-08-24",
                sport=None,
                training_load=50.0,
            ).to_row(include_none=True),
            ["source", "source_id"],
        )
        payload = build_training_payload(conn, _CONFIG)
        assert payload["load_by_sport"] == [
            {"date": "2026-08-24", "sport": "unknown", "load": 50.0}
        ]

    def test_recent_calisthenics_includes_exercises(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "calisthenics_sessions",
            CalisthenicsSession(
                date="2026-08-24",
                session_type="strength_a",
                session_rpe=6,
                exercises=[
                    {
                        "exercise": "pull-ups",
                        "sets": 4,
                        "reps": 5,
                        "added_weight_kg": None,
                        "notes": None,
                    }
                ],
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG)
        assert len(payload["calisthenics"]) == 1
        assert payload["calisthenics"][0]["exercises"][0]["exercise"] == "pull-ups"

    def test_recent_calisthenics_empty_when_none_logged(self, conn: sqlite3.Connection) -> None:
        payload = build_training_payload(conn, _CONFIG)
        assert payload["calisthenics"] == []
