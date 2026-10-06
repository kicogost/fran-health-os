from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from health_os.api.fitness import build_fitness_payload
from health_os.core import db
from health_os.core.models import Activity, ActivityAutoSegment, DailyMetric

CONFIG = {"fitness": {"hr_max_bpm": 200}}
START = date(2026, 1, 1)


def _day(offset: int) -> str:
    return (START + timedelta(days=offset)).isoformat()


def _seed_daily(conn: sqlite3.Connection) -> None:
    for i in range(0, 131):
        metric = DailyMetric(date=_day(i), resting_hr=50, hrv_overnight_ms=90.0)
        if i == 60:
            metric = DailyMetric(date=_day(i), resting_hr=50, hrv_overnight_ms=90.0, vo2max=52.0)
        db.upsert(conn, "daily_metrics", metric.to_row(), ["date"])


def _seed_bjj(conn: sqlite3.Connection, offset: int) -> None:
    activity = Activity(
        activity_id=f"garmin:{offset}",
        source="garmin",
        source_id=str(offset),
        start_utc=f"{_day(offset)}T17:00:00Z",
        local_date=_day(offset),
        sport="other",
        sub_sport="bjj",
    )
    db.upsert(conn, "activities", activity.to_row(), ["activity_id"])
    for i, (label, start, end, hr) in enumerate(
        [("round", 0, 300, 185), ("rest", 300, 360, 165), ("round", 360, 660, 180)]
    ):
        segment = ActivityAutoSegment(
            activity_id=activity.activity_id,
            segment_index=i,
            start_s=start,
            end_s=end,
            label=label,
            avg_hr=hr,
        )
        db.upsert(
            conn, "activity_auto_segments", segment.to_row(), ["activity_id", "segment_index"]
        )


class TestBuildFitnessPayload:
    def test_real_inputs_flow_through(self, conn: sqlite3.Connection) -> None:
        _seed_daily(conn)
        payload = build_fitness_payload(conn, CONFIG, _day(130))
        assert payload["latest_measurement"]["value"] == 52.0
        # factor 52 x 50/200 = 13.0 -> steady RHR 50 -> estimate 52.0
        assert payload["current"]["value"] == pytest.approx(52.0)
        assert payload["hr_max"] == 200.0

    def test_bjj_recovery_is_context_per_session(self, conn: sqlite3.Connection) -> None:
        _seed_daily(conn)
        _seed_bjj(conn, 100)
        _seed_bjj(conn, 200)  # after as_of -- must not leak in
        payload = build_fitness_payload(conn, CONFIG, _day(130))
        assert payload["bjj_recovery"] == [{"date": _day(100), "avg_drop_bpm": 20.0}]

    def test_empty_database(self, conn: sqlite3.Connection) -> None:
        payload = build_fitness_payload(conn, CONFIG, _day(130))
        assert payload["latest_measurement"] is None
        assert payload["bjj_recovery"] == []
