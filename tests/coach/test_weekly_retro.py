from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from health_os.coach.weekly_retro import compute_weekly_retro, format_weekly_retro
from health_os.core import db
from health_os.core.models import (
    Activity,
    BjjSession,
    BodyMeasurement,
    DailyMetric,
    SubjectiveLogEntry,
)

WEEK_ENDING = "2026-08-30"  # a Sunday
WEEK_START = "2026-08-24"

_CONFIG = {
    "comp_prep": {
        "weekly_template": [
            {
                "day": "monday",
                "sessions": [
                    {"type": "bjj", "subtype": "no_gi_technical"},
                    {"type": "calisthenics", "subtype": "strength_a"},
                ],
            },
            {"day": "tuesday", "sessions": [{"type": "bjj", "subtype": "hard_rounds"}]},
            {"day": "wednesday", "sessions": [{"type": "bjj", "subtype": "no_gi_technical"}]},
            {"day": "thursday", "sessions": [{"type": "rest"}]},
            {"day": "friday", "sessions": [{"type": "bjj", "subtype": "open_mat"}]},
            {"day": "saturday", "sessions": [{"type": "bike", "subtype": "easy_z2"}]},
            {"day": "sunday", "sessions": [{"type": "rest"}]},
        ]
    },
    "training_load": {"bjj_rpe_calibration_factor": 1.0},
}


def _seed_weight(conn: sqlite3.Connection, values: dict[str, float]) -> None:
    for d, kg in values.items():
        db.upsert(conn, "daily_metrics", DailyMetric(date=d, weight_kg=kg).to_row(), ["date"])


class TestSessionCompletion:
    def test_bjj_completed_and_missed(self, conn: sqlite3.Connection) -> None:
        # Monday (2026-08-24) logged, Wednesday (2026-08-26) not.
        db.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-08-24", session_type="class", duration_min=90, session_rpe=7
            ).to_row(),
            ["date", "session_type"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        by_date = {(s["date"], s["type"]): s["status"] for s in plan["sessions"]}
        assert by_date[("2026-08-24", "bjj")] == "completed"
        assert by_date[("2026-08-26", "bjj")] == "missed"

    def test_calisthenics_is_not_trackable_not_missed(self, conn: sqlite3.Connection) -> None:
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        by_date = {(s["date"], s["type"]): s["status"] for s in plan["sessions"]}
        assert by_date[("2026-08-24", "calisthenics")] == "not_trackable"

    def test_bike_from_activities_table(self, conn: sqlite3.Connection) -> None:
        db.upsert(
            conn,
            "activities",
            Activity(
                activity_id="garmin:1",
                source="garmin",
                source_id="1",
                start_utc="2026-08-29T07:00:00Z",
                local_date="2026-08-29",
                sport="cycling",
            ).to_row(),
            ["source", "source_id"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        by_date = {(s["date"], s["type"]): s["status"] for s in plan["sessions"]}
        assert by_date[("2026-08-29", "bike")] == "completed"

    def test_bike_missing_is_missed(self, conn: sqlite3.Connection) -> None:
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        by_date = {(s["date"], s["type"]): s["status"] for s in plan["sessions"]}
        assert by_date[("2026-08-29", "bike")] == "missed"

    def test_rest_days_are_na(self, conn: sqlite3.Connection) -> None:
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        by_date = {(s["date"], s["type"]): s["status"] for s in plan["sessions"]}
        assert by_date[("2026-08-27", "rest")] == "n/a"


class TestWeightTrend:
    def test_uses_7_day_window_not_21(self, conn: sqlite3.Connection) -> None:
        # A clean, steady +0.1kg/day over the trailing week only.
        start = date.fromisoformat(WEEK_START)
        values = {(start + timedelta(days=i)).isoformat(): 80.0 + i * 0.1 for i in range(7)}
        _seed_weight(conn, values)
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["weight_trend"]["confidence"] == "full"
        assert plan["weight_trend"]["window_days"] == 7

    def test_insufficient_data(self, conn: sqlite3.Connection) -> None:
        _seed_weight(conn, {"2026-08-30": 80.0})
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["weight_trend"]["confidence"] == "insufficient_data"


class TestProteinAdherence:
    def test_rate_only_over_logged_days(self, conn: sqlite3.Connection) -> None:
        db.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(date="2026-08-24", protein_hit=True).to_row(),
            ["date"],
        )
        db.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(date="2026-08-25", protein_hit=False).to_row(),
            ["date"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["protein_days_logged"] == 2
        assert plan["protein_adherence_rate"] == 0.5

    def test_no_data_logged(self, conn: sqlite3.Connection) -> None:
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["protein_adherence_rate"] is None
        assert plan["protein_days_logged"] == 0


class TestSocialMealCount:
    def test_counts_true_only(self, conn: sqlite3.Connection) -> None:
        db.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(date="2026-08-24", social_meal=True).to_row(),
            ["date"],
        )
        db.upsert(
            conn,
            "subjective_log",
            SubjectiveLogEntry(date="2026-08-25", social_meal=False).to_row(),
            ["date"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["social_meal_count"] == 1


class TestWaistDelta:
    def test_delta_between_last_two_measurements(self, conn: sqlite3.Connection) -> None:
        db.upsert(
            conn,
            "body_measurements",
            BodyMeasurement(date="2026-08-17", value_cm=86.0).to_row(),
            ["date", "measurement_type"],
        )
        db.upsert(
            conn,
            "body_measurements",
            BodyMeasurement(date="2026-08-24", value_cm=85.2).to_row(),
            ["date", "measurement_type"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["waist_delta_cm"] == pytest.approx(85.2 - 86.0)

    def test_insufficient_measurements(self, conn: sqlite3.Connection) -> None:
        db.upsert(
            conn,
            "body_measurements",
            BodyMeasurement(date="2026-08-24", value_cm=85.2).to_row(),
            ["date", "measurement_type"],
        )
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        assert plan["waist_delta_cm"] is None


class TestFormatWeeklyRetro:
    def test_produces_readable_text_without_crashing(self, conn: sqlite3.Connection) -> None:
        plan = compute_weekly_retro(conn, _CONFIG, WEEK_ENDING)
        text = format_weekly_retro(plan)
        assert "Weekly retro" in text
        assert "Calisthenics progression: not trackable" in text
        assert "Sessions:" in text
