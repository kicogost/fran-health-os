"""Tests for coach/briefing.py — until 2026-08-28 this module (the single
most complex assembly point in the coaching layer) had ZERO test coverage,
a real gap that let a future-data-leakage bug through review undetected.
Focused on `compute_daily_plan()`'s date-bounding contract, plus a basic
smoke test of the overall shape.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from health_os.coach.briefing import build_briefing, compute_daily_plan
from health_os.core import db as db_module
from health_os.core.models import BjjSession, DailyMetric
from health_os.metrics.baselines import DEFAULT_BASELINE_WINDOW_DAYS

_CONFIG = {
    "comp_prep": {
        "weekly_template": [
            {"day": "monday", "sessions": [{"type": "bjj", "subtype": "no_gi_technical"}]},
            {"day": "tuesday", "sessions": [{"type": "rest"}]},
            # Wednesday deliberately absent -- a real "nothing scheduled" day,
            # distinct from an explicit "rest" entry.
        ]
    },
    "training_load": {"bjj_rpe_calibration_factor": 1.0},
    "readiness_score": {
        "weight_hrv": 0.35,
        "weight_sleep": 0.25,
        "weight_rhr": 0.15,
        "weight_subjective": 0.25,
    },
    "nutrition": {"protein_g_daily_min": 180},
    "goals": {"primary": {"date": "2026-10-18", "weight_division_kg": 77.0}},
}


def _date_range(end: date, n_days: int) -> list[date]:
    """The `n_days` dates ending on (and including) `end`, ascending."""
    return [end - timedelta(days=i) for i in range(n_days - 1, -1, -1)]


class TestComputeDailyPlanDateBounding:
    def test_structural_flags_do_not_leak_future_hrv_data(self, conn: sqlite3.Connection) -> None:
        # Real bug found 2026-08-28: hrv_sustained_low (and the other
        # structural flags) were computed from an UNBOUNDED daily_rows
        # fetch, so calling compute_daily_plan() with a past `today` while
        # the DB already has LATER rows (the normal state days after the
        # fact) could leak future HRV data into "as of today"'s flags.
        #
        # Needs >= DEFAULT_BASELINE_WINDOW_DAYS (60) stable days to reach the
        # "computed" baseline phase (below that, compute_hrv_baseline() is
        # still in its seed phase and has no deviation_sd / "full" confidence
        # at all, which would make this test vacuous).
        as_of = date(2026, 8, 4)
        for d in _date_range(as_of, DEFAULT_BASELINE_WINDOW_DAYS):
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d.isoformat(), hrv_overnight_ms=90.0).to_row(),
                ["date"],
            )
        for offset, hrv in enumerate([60.0, 58.0, 55.0], start=1):
            future_date = (as_of + timedelta(days=offset)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=future_date, hrv_overnight_ms=hrv).to_row(),
                ["date"],
            )

        plan = compute_daily_plan(conn, _CONFIG, as_of.isoformat())

        assert plan["structural_flags"]["hrv_sustained_low"] is False
        # The score-path component must agree with the flag -- both derived
        # from the same "as of" date, so a stable HRV history must NOT be
        # reported as low by either path.
        assert plan["score_result"]["components"]["hrv"]["raw"] == 0.0

    def test_trend_observation_does_not_leak_future_rhr_data(
        self, conn: sqlite3.Connection
    ) -> None:
        # Same bug, via _notable_trend_observation()'s RHR sustained-rise
        # check: stable RHR history through the as-of date, then a real
        # 3-day rise logged AFTER it -- must not surface as "today"'s trend.
        as_of = date(2026, 8, 4)
        for d in _date_range(as_of, 25):  # RHR baseline's own min_days is 21
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d.isoformat(), resting_hr=50.0).to_row(),
                ["date"],
            )
        for offset, rhr in enumerate([60.0, 61.0, 62.0], start=1):
            future_date = (as_of + timedelta(days=offset)).isoformat()
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=future_date, resting_hr=rhr).to_row(),
                ["date"],
            )

        plan = compute_daily_plan(conn, _CONFIG, as_of.isoformat())
        assert plan["trend_observation"] is None

    def test_monotony_strain_flag_does_not_leak_future_load(self, conn: sqlite3.Connection) -> None:
        as_of = "2026-07-10"
        # A BJJ session logged well AFTER the as-of date must not affect
        # today's monotony/strain read.
        db_module.upsert(
            conn,
            "bjj_sessions",
            BjjSession(
                date="2026-07-15", session_type="class", duration_min=90, session_rpe=9
            ).to_row(),
            ["date", "session_type"],
        )
        plan = compute_daily_plan(conn, _CONFIG, as_of)
        # No crash, and a date with no load data at all as of that day can't
        # be flagged high-monotony -- the real assertion is that the future
        # session (logged 5 days later) has zero effect on this result.
        assert plan["structural_flags"]["monotony_strain"] is False


class TestComputeDailyPlanShape:
    def test_basic_smoke(self, conn: sqlite3.Connection) -> None:
        plan = compute_daily_plan(conn, _CONFIG, "2026-08-24")  # a Monday
        assert plan["today"] == "2026-08-24"
        assert plan["weekday_name"] == "monday"
        assert plan["band"] in ("no_data", "red", "amber", "green")
        assert len(plan["sessions"]) == 1
        assert plan["sessions"][0]["type"] == "bjj"
        assert plan["nutrition_focus"].startswith("Hit 180g protein")

    def test_explicit_rest_day_has_one_rest_session(self, conn: sqlite3.Connection) -> None:
        plan = compute_daily_plan(conn, _CONFIG, "2026-08-25")  # a Tuesday
        assert len(plan["sessions"]) == 1
        assert plan["sessions"][0]["type"] == "rest"

    def test_day_with_no_template_entry_has_no_sessions(self, conn: sqlite3.Connection) -> None:
        plan = compute_daily_plan(conn, _CONFIG, "2026-08-26")  # a Wednesday, not in _CONFIG
        assert plan["sessions"] == []

    def test_garmin_sleep_score_actually_reaches_the_sleep_component(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real gap found 2026-08-30: our own duration+debt sleep score read
        # 97 the same night Garmin's quality-aware score read 74 -- fixed by
        # blending Garmin's sleep_score in. This locks in the actual wiring
        # (briefing.py fetching daily_metrics.sleep_score and passing it
        # through), not just the pure formula tested in test_readiness.py.
        db_module.upsert(
            conn,
            "daily_metrics",
            DailyMetric(date="2026-08-24", sleep_total_min=449, sleep_score=74).to_row(),
            ["date"],
        )
        plan = compute_daily_plan(conn, _CONFIG, "2026-08-24")
        sleep_component = plan["score_result"]["components"].get("sleep")
        assert sleep_component is not None
        assert sleep_component["raw"]["quality_score"] == 74

    def test_taper_day_override_actually_replaces_the_weekly_template(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real gap closed 2026-08-30: config/athlete.yaml's hand-planned
        # taper week (comp_prep.blocks[].daily_schedule) existed since
        # 2026-08-27 but nothing ever read it -- this locks in the actual
        # wiring through compute_daily_plan(), not just taper_day_override()
        # tested in isolation.
        config = {
            **_CONFIG,
            "comp_prep": {
                **_CONFIG["comp_prep"],
                "blocks": [
                    {
                        "name": "taper",
                        "starts": "2026-10-12",
                        "ends": "2026-10-18",
                        "daily_schedule": [
                            {
                                "date": "2026-10-12",
                                "day": "monday",
                                "plan": "BJJ, technical, 60% effort",
                            }
                        ],
                    }
                ],
            },
        }
        # 2026-10-12 is a Monday -- the generic weekly_template would
        # otherwise schedule a real BJJ + calisthenics day here.
        plan = compute_daily_plan(conn, config, "2026-10-12")
        assert len(plan["sessions"]) == 1
        assert plan["sessions"][0]["type"] == "taper"
        assert plan["sessions"][0]["instruction"] == "BJJ, technical, 60% effort"
        assert plan["taper"]["active"] is True
        assert plan["taper"]["days_to_competition"] == 6

    def test_deload_triggers_through_the_full_pipeline_with_real_seeded_data(
        self, conn: sqlite3.Connection
    ) -> None:
        # Two real markers seeded through actual daily_metrics/subjective_log
        # rows, not constructed rules.py inputs -- proves the wiring, not
        # just should_deload()'s own arithmetic.
        as_of = date(2026, 8, 30)
        # 60 stable baseline days, then 6 days with elevated RHR (>1 SD
        # above baseline, matching compute_rhr_baseline()'s own
        # sustained_rise_flag window) AND a matching Hooper-index streak.
        for i, d in enumerate(_date_range(as_of, 66)):
            rhr = 65.0 if i >= 60 else 50.0
            db_module.upsert(
                conn,
                "daily_metrics",
                DailyMetric(date=d.isoformat(), resting_hr=rhr).to_row(),
                ["date"],
            )
        for d in _date_range(as_of, 3):
            db_module.upsert(
                conn,
                "subjective_log",
                {
                    "date": d.isoformat(),
                    "sleep_quality": 9,
                    "stress": 9,
                    "fatigue": 9,
                    "muscle_soreness": 8,
                    "hooper_index": 35,
                },
                ["date"],
            )
        plan = compute_daily_plan(conn, _CONFIG, as_of.isoformat())
        assert "rhr_sustained_rise" in plan["deload"]["markers_fired"]
        assert "hooper_sustained_high" in plan["deload"]["markers_fired"]
        assert plan["deload"]["recommended"] is True


class TestBuildBriefing:
    def test_produces_readable_text(self, conn: sqlite3.Connection) -> None:
        text = build_briefing(conn, _CONFIG, "2026-08-24")
        assert "Health OS briefing — 2026-08-24 (Monday)" in text
        assert "Readiness:" in text
        assert "Nutrition:" in text

    def test_day_with_no_template_entry_says_nothing_scheduled(
        self, conn: sqlite3.Connection
    ) -> None:
        text = build_briefing(conn, _CONFIG, "2026-08-26")  # Wednesday, not in _CONFIG
        assert "Nothing scheduled today." in text
