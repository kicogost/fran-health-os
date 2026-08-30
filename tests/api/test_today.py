"""Tests for api/today.py — the pure assembly function behind the FastAPI
/api/today route (ADR 0005 frontend migration).
"""

from __future__ import annotations

import sqlite3

from health_os.api.today import (
    _annotate_components_with_display,
    _format_hours_minutes,
    build_today_payload,
)
from health_os.core import db as db_module
from health_os.core.models import DailyMetric

_CONFIG = {
    "profile": {"age": 24},
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

    def test_taper_and_deload_included_in_payload(self, conn: sqlite3.Connection) -> None:
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert "days_to_competition" in payload["taper"]
        assert payload["deload"]["recommended"] is False
        assert payload["deload"]["duration_days"] == 6
        assert payload["deload"]["volume_reduction_pct"] == 40

    def test_strain_included_in_payload(self, conn: sqlite3.Connection) -> None:
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert "strain" in payload
        assert payload["strain"]["strain"] is None  # no activities/bjj logged that date

    def test_strain_reflects_a_real_logged_bjj_session(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "bjj_sessions",
            {
                "date": "2026-08-24",
                "session_type": "open_mat",
                "duration_min": 90,
                "session_rpe": 8,
            },
            ["date", "session_type"],
        )
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert payload["strain"]["strain"] is not None
        assert payload["strain"]["components"][0]["method"] == "foster_estimated"

    def test_readiness_components_are_json_serializable_shape(
        self, conn: sqlite3.Connection
    ) -> None:
        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        assert isinstance(payload["readiness"]["components"], dict)
        assert isinstance(payload["structural_flags"], dict)

    def test_readiness_components_carry_display_raw_end_to_end(
        self, conn: sqlite3.Connection
    ) -> None:
        # Integration-level version of TestAnnotateComponentsWithDisplay --
        # confirms the wiring through the real route function, not just the
        # helper in isolation. Needs real seeded history, not one day: with
        # too little history `components` comes back empty and an
        # `if "hrv" in components` check would pass vacuously without
        # proving anything (caught while writing this). HRV specifically
        # needs 60+ days (its "seed" phase, 21-59 days, never populates
        # deviation_sd at all -- only the full 60-day computed baseline
        # does, per metrics/baselines.py), unlike RHR which has no such
        # seed phase and reaches full confidence at 21.
        from datetime import date, timedelta

        target = date(2026, 8, 24)
        for days_back in range(60, 0, -1):  # 60 consecutive days before the target, no gap
            d = (target - timedelta(days=days_back)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d, hrv_overnight_ms=88.0, resting_hr=50.0).to_row(),
                ["date"],
            )
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-24", hrv_overnight_ms=90.0, resting_hr=52.0).to_row(),
            ["date"],
        )

        payload = build_today_payload(conn, _CONFIG, "2026-08-24")
        components = payload["readiness"]["components"]
        assert "hrv" in components and "rhr" in components  # sanity: not a vacuous check
        assert components["hrv"]["display_raw"] == "90ms"
        assert components["rhr"]["display_raw"] == "52bpm"


class TestFormatHoursMinutes:
    def test_formats_with_leading_zero_minutes(self) -> None:
        assert _format_hours_minutes(449) == "7h29m"
        assert _format_hours_minutes(360) == "6h00m"

    def test_none_stays_none(self) -> None:
        assert _format_hours_minutes(None) is None


class TestAnnotateComponentsWithDisplay:
    """Real bug found 2026-08-30: the dashboard's component rings ("HRV 47",
    "RHR 24") are the 0-100 readiness sub-score, never the raw sensor
    reading -- Francisco reasonably read them as raw HRV ms / RHR bpm since
    nothing on the page ever showed the actual number. These tests lock in
    the fix: a real, human-readable raw value alongside the score.
    """

    def _daily_row(self, conn: sqlite3.Connection, date: str, **fields) -> sqlite3.Row:
        db_module.upsert(conn, "daily_metrics", DailyMetric(date=date, **fields).to_row(), ["date"])
        return conn.execute("SELECT * FROM daily_metrics WHERE date = ?", (date,)).fetchone()

    def test_hrv_gets_a_real_ms_display(self, conn: sqlite3.Connection) -> None:
        row = self._daily_row(conn, "2026-08-30", hrv_overnight_ms=90.0)
        components = {"hrv": {"raw": -0.11, "score": 47.3, "weight_used": 0.35}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["hrv"]["display_raw"] == "90ms"
        assert annotated["hrv"]["score"] == 47.3  # original fields preserved

    def test_rhr_gets_a_real_bpm_display(self, conn: sqlite3.Connection) -> None:
        row = self._daily_row(conn, "2026-08-30", resting_hr=52.0)
        components = {"rhr": {"raw": 1.04, "score": 24.1, "weight_used": 0.15}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["rhr"]["display_raw"] == "52bpm"

    def test_sleep_gets_a_real_hours_minutes_display(self, conn: sqlite3.Connection) -> None:
        row = self._daily_row(conn, "2026-08-30", sleep_total_min=449)
        components = {"sleep": {"raw": {}, "score": 96.8, "weight_used": 0.25}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["sleep"]["display_raw"] == "7h29m"

    def test_sleep_display_includes_garmin_score_when_present(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real gap found 2026-08-30: the ring's own number now blends
        # Garmin's quality score in (metrics/readiness.py), so the caption
        # should show both real inputs behind it, not just duration.
        row = self._daily_row(conn, "2026-08-30", sleep_total_min=449, sleep_score=74)
        components = {"sleep": {"raw": {}, "score": 85.5, "weight_used": 0.25}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["sleep"]["display_raw"] == "7h29m · Garmin 74"

    def test_missing_raw_value_gives_none_not_a_crash(self, conn: sqlite3.Connection) -> None:
        row = self._daily_row(conn, "2026-08-30")
        components = {"hrv": {"raw": -0.11, "score": 47.3, "weight_used": 0.35}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["hrv"]["display_raw"] is None

    def test_zero_weight_used_marked_excluded(self, conn: sqlite3.Connection) -> None:
        # Companion fix: config/athlete.yaml's weight_tsb temporarily 0.0
        # (real coverage-gap bug, see CLAUDE.md) means TSB shows up with
        # weight_used=0.0 -- it must read as visibly excluded, not as a
        # real, counted score of 0.
        row = self._daily_row(conn, "2026-08-30")
        components = {"tsb": {"raw": -3.08, "score": 0.0, "weight_used": 0.0}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["tsb"]["excluded"] is True

    def test_nonzero_weight_used_not_excluded(self, conn: sqlite3.Connection) -> None:
        row = self._daily_row(conn, "2026-08-30")
        components = {"hrv": {"raw": -0.11, "score": 47.3, "weight_used": 0.35}}
        annotated = _annotate_components_with_display(components, row)
        assert annotated["hrv"]["excluded"] is False

    def test_no_daily_row_at_all_does_not_crash(self) -> None:
        components = {"hrv": {"raw": -0.11, "score": 47.3, "weight_used": 0.35}}
        annotated = _annotate_components_with_display(components, None)
        assert annotated["hrv"]["display_raw"] is None
