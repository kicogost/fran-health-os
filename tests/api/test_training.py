from __future__ import annotations

import json
import sqlite3

from health_os.api.training import build_training_payload
from health_os.core import db as db_module
from health_os.core.models import BjjSession, CalisthenicsSession

_CONFIG = {"profile": {"age": 24}, "training_load": {"bjj_rpe_calibration_factor": 1.0}}


class TestBuildTrainingPayload:
    def test_no_load_data_reports_has_load_data_false(self, conn: sqlite3.Connection) -> None:
        # No daily_metrics.resting_hr history at all -- the real
        # prerequisite for a TRIMP-based series (2026-08-30 rebuild).
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["has_load_data"] is False
        assert payload["ctl_atl_tsb"] == []
        assert payload["tsb_zscore"] is None
        assert payload["monotony_strain"] is None
        assert payload["load_by_sport"] == []

    def test_resting_hr_alone_is_enough_for_has_load_data(self, conn: sqlite3.Connection) -> None:
        # Real behavior change from the pre-2026-08-30 version: a real rest
        # day (resting_hr known, nothing else) now produces a genuine 0.0
        # series entry, not "no data at all."
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["has_load_data"] is True
        assert payload["ctl_atl_tsb"] == [
            {"date": "2026-08-24", "ctl": 0.0, "atl": 0.0, "tsb": 0.0}
        ]

    def test_bjj_load_populates_ctl_atl_tsb(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
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
        assert payload["ctl_atl_tsb"][0]["ctl"] > 0.0

    def test_activity_with_avg_hr_contributes_trimp_based_load(
        self, conn: sqlite3.Connection
    ) -> None:
        # The real point of the 2026-08-30 rebuild: a bike ride with a real
        # avg_hr (no activities.training_load needed at all) now shows up.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:ride1",
                "source": "garmin",
                "source_id": "ride1",
                "start_utc": "2026-08-24T06:00:00Z",
                "local_date": "2026-08-24",
                "sport": "cycling",
                "duration_s": 6420,
                "avg_hr": 143,
            },
            ["activity_id"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["ctl_atl_tsb"][0]["ctl"] > 0.0
        assert payload["load_by_sport"] == [
            {"date": "2026-08-24", "sport": "cycling", "load": payload["load_by_sport"][0]["load"]}
        ]
        assert payload["load_by_sport"][0]["load"] > 0.0

    def test_load_by_sport_fills_null_sport_as_unknown(self, conn: sqlite3.Connection) -> None:
        # Real gap this session already found and fixed on the Streamlit
        # side (training.py): pandas groupby(dropna=True) silently drops
        # NULL-sport activities. Must not repeat it here either.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:1",
                "source": "garmin",
                "source_id": "1",
                "start_utc": "2026-08-24T06:00:00Z",
                "local_date": "2026-08-24",
                "sport": None,
                "duration_s": 3600,
                "avg_hr": 140,
            },
            ["activity_id"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["load_by_sport"][0]["sport"] == "unknown"

    def test_load_by_sport_includes_bjj_labeled_bjj(self, conn: sqlite3.Connection) -> None:
        # Real bug fixed 2026-08-30: the old query only ever read
        # activities.training_load, so a real BJJ session that clearly
        # moved the CTL/ATL/TSB chart and weekly-load stat above it never
        # showed up in this sport breakdown at all.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=8
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["load_by_sport"] == [{"date": "2026-08-24", "sport": "bjj", "load": 216.0}]

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

    def test_weekly_summary_present_and_counts_real_sessions(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=8
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["weekly_summary"]["session_count"] == 1
        assert payload["weekly_summary"]["total_minutes"] == 90.0

    def test_insights_present_even_with_no_data(self, conn: sqlite3.Connection) -> None:
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        assert payload["insights"]["fitness_trend"]["tone"] == "unknown"
        assert payload["insights"]["freshness"]["tone"] == "unknown"
        assert payload["insights"]["consistency"]["tone"] == "unknown"

    def test_insights_never_mention_the_old_acronyms(self, conn: sqlite3.Connection) -> None:
        # Real ask, 2026-08-30: "no fluff no acronyms" -- lock this in so a
        # future change can't silently reintroduce CTL/ATL/TSB jargon here.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-24", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=8
            ).to_row(),
            ["date", "session_type"],
        )
        payload = build_training_payload(conn, _CONFIG, "2026-08-24")
        blob = json.dumps(payload["insights"]).lower()
        for banned in ("ctl", "atl", "tsb", "monotony"):
            assert banned not in blob
