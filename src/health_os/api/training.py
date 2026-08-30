"""Assembles the Training page's payload — CTL/ATL/TSB, monotony/strain,
load by day/sport, recent calisthenics sessions.

**Rebuilt 2026-08-30** (Francisco: "why can't you show the bikes, and once I
start measuring my BJJ sessions, the sessions as well?"). Previously, every
number on this page was fed by `activities.training_load` — Garmin/Strava's
own, largely NULL, opaque-unit column (CLAUDE.md's training-load build-out
notes: only 9 old Strava runs, pre-June 2026, ever had one). Bike rides,
Garmin-recorded BJJ, and strength sessions all have a real, usable `avg_hr`
on this account — they just never had that specific column populated. Now
built entirely from `metrics.strain.build_activity_based_load_series()`/
`build_load_by_sport_rows()`: TRIMP (Banister 1991) wherever a real `avg_hr`
exists, Foster's method for BJJ manual logs not already covered by a real
matching activity — the SAME per-day computation the Daily Strain ring
already uses, so this page and Today's Strain ring can never independently
disagree about what a day's real training consisted of.

A real, separate bug fixed in the same pass (found while investigating the
above): `_load_by_sport()`'s predecessor only ever read `activities.
training_load`, so a real BJJ session that clearly moved the CTL/ATL/TSB
chart and weekly-load stat above it never showed up in the sport breakdown
at all. Gone now — both come from the same per-day components.

**Plain-language rework, same day, immediately after** (Francisco: "i need
more visuals and you need to tell me things in layman terms, not ctl, atl
etc... no fluff no acronyms"). `insights` (`metrics/insights.py`) reframes
CTL -> a plain fitness-trend sentence, TSB -> a plain, self-relative
freshness read, and monotony -> a plain consistency sentence — never CTL/
ATL/TSB/monotony/strain by name anywhere in the payload's own text.
`weekly_summary` is a real, understandable "N sessions, X hours this week"
built from the same per-day components, replacing the raw "weekly load"
number as the headline weekly stat. The raw `ctl_atl_tsb`/`tsb_zscore`/
`monotony_strain` fields are NOT removed — design principle 9 (every number
traceable) still applies, they're just no longer what the page leads with;
the frontend surfaces them as an optional, secondary "technical detail"
section rather than the primary view.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from health_os.metrics import insights as insights_module
from health_os.metrics import load as load_metrics
from health_os.metrics import strain as strain_metrics


def _recent_calisthenics(conn: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT date, session_type, session_rpe, exercises_json FROM calisthenics_sessions "
        "ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "date": r["date"],
            "session_type": r["session_type"],
            "session_rpe": r["session_rpe"],
            "exercises": json.loads(r["exercises_json"]) if r["exercises_json"] else [],
        }
        for r in rows
    ]


def build_training_payload(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> dict[str, Any]:
    """Everything the Training page needs, as one JSON-ready dict.
    `as_of_date` is required (not read from the clock here) — same
    convention as `coach.briefing.compute_daily_plan()`.

    `has_load_data` now means "is there enough `daily_metrics.resting_hr`
    history to build a TRIMP-based series at all" (the real prerequisite
    for `build_activity_based_load_series()`), not "did any activity happen
    to have a `training_load` value" — a real, honest, differently-scoped
    meaning than before, since the new series always answers every day in
    range, including genuine, real 0.0 rest days.
    """
    daily_load_series = strain_metrics.build_activity_based_load_series(conn, config, as_of_date)

    payload: dict[str, Any] = {
        "has_load_data": bool(daily_load_series),
        "ctl_atl_tsb": [],
        "tsb_zscore": None,
        "monotony_strain": None,
        "load_by_sport": strain_metrics.build_load_by_sport_rows(conn, config, as_of_date),
        "calisthenics": _recent_calisthenics(conn),
        "weekly_summary": strain_metrics.build_weekly_summary(conn, config, as_of_date),
        "insights": {
            "fitness_trend": insights_module.fitness_trend_insight([]),
            "freshness": insights_module.freshness_insight({"confidence": "insufficient_data"}),
            "consistency": insights_module.consistency_insight(None),
        },
    }

    if daily_load_series:
        ctl_atl_tsb = load_metrics.compute_ctl_atl(daily_load_series)
        payload["ctl_atl_tsb"] = [
            {"date": d, "ctl": ctl, "atl": atl, "tsb": tsb} for d, ctl, atl, tsb in ctl_atl_tsb
        ]
        ctl_series = [(d, ctl) for d, ctl, _atl, _tsb in ctl_atl_tsb]
        tsb_series = [(d, tsb) for d, _ctl, _atl, tsb in ctl_atl_tsb]
        tsb_zscore = load_metrics.compute_tsb_zscore(tsb_series)
        monotony_strain = load_metrics.compute_monotony_strain(daily_load_series)
        payload["tsb_zscore"] = tsb_zscore
        payload["monotony_strain"] = monotony_strain
        payload["insights"] = {
            "fitness_trend": insights_module.fitness_trend_insight(ctl_series),
            "freshness": insights_module.freshness_insight(tsb_zscore),
            "consistency": insights_module.consistency_insight(monotony_strain),
        }

    return payload
