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
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

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
    }

    if daily_load_series:
        ctl_atl_tsb = load_metrics.compute_ctl_atl(daily_load_series)
        payload["ctl_atl_tsb"] = [
            {"date": d, "ctl": ctl, "atl": atl, "tsb": tsb} for d, ctl, atl, tsb in ctl_atl_tsb
        ]
        tsb_series = [(d, tsb) for d, _ctl, _atl, tsb in ctl_atl_tsb]
        payload["tsb_zscore"] = load_metrics.compute_tsb_zscore(tsb_series)
        payload["monotony_strain"] = load_metrics.compute_monotony_strain(daily_load_series)

    return payload
