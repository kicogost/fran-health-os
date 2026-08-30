from __future__ import annotations

import sqlite3

from health_os.api.training import build_training_payload
from health_os.core import db as db_module
from health_os.core.models import Activity, BjjSession, CalisthenicsSession

_CONFIG = {"training_load": {"bjj_rpe_calibration_factor": 1.0}}


class TestBuildTrainingPayload:
    def test_no_load_data_reports_has_load_data_false(self, conn: sqlite3.Connection) -> None:
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["has_load_data"] is False
        assert payload["is_stale"] is False
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
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["has_load_data"] is True
        assert len(payload["ctl_atl_tsb"]) == 1
        assert payload["ctl_atl_tsb"][0]["date"] == "2026-08-24"

    def test_fresh_load_data_is_not_stale(self, conn: sqlite3.Connection) -> None:
        # Same day as as_of_date -- 0 days stale.
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["is_stale"] is False
        assert payload["days_stale"] == 0

    def test_old_load_data_is_flagged_stale(self, conn: sqlite3.Connection) -> None:
        # Real motivating case: a single old BJJ log is enough to flip
        # has_load_data True, but the chart it feeds is describing a load
        # series that stopped updating months ago -- must not render with
        # zero caveat (Francisco: "why don't my bike rides show up" / "I
        # don't know what this means" -- this is the fix for the silent
        # half of that confusion, the plain-language half is the frontend's
        # job).
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-06-01", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["has_load_data"] is True
        assert payload["is_stale"] is True
        assert payload["days_stale"] == 84

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
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["load_by_sport"] == [
            {"date": "2026-08-24", "sport": "unknown", "load": 50.0}
        ]

    def test_load_by_sport_includes_bjj(self, conn: sqlite3.Connection) -> None:
        # Real bug fixed 2026-08-30: this query only ever read
        # activities.training_load, so a real BJJ session that clearly
        # moved the CTL/ATL/TSB chart and weekly-load stat above it never
        # showed up in this sport breakdown at all -- the two numbers on
        # the same page silently disagreed about what "load" included.
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=8
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["load_by_sport"] == [{"date": "2026-08-24", "sport": "bjj", "load": 720.0}]

    def test_load_by_sport_scales_bjj_by_calibration_factor(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=8
            ).to_row(),
            ["date", "session_type"],
        )
        config = {"training_load": {"bjj_rpe_calibration_factor": 0.5}}
        payload = build_training_payload(conn, config, "2026-08-24")
        assert payload["load_by_sport"] == [{"date": "2026-08-24", "sport": "bjj", "load": 360.0}]

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
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert len(payload["calisthenics"]) == 1
        assert payload["calisthenics"][0]["exercises"][0]["exercise"] == "pull-ups"

    def test_recent_calisthenics_empty_when_none_logged(self, conn: sqlite3.Connection) -> None:
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["calisthenics"] == []
