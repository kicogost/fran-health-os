"""Assembles the Training page's payload — CTL/ATL/TSB, monotony/strain,
load by day/sport, recent calisthenics sessions. Mirrors
`dashboard/views/training.py`, including its own honest "no training_load
data yet" state rather than an empty/misleading chart (see CLAUDE.md's
training-load build-out notes for why that's a real, current condition on
this account, not a bug).

**A second, narrower honesty gap fixed 2026-08-30**: `has_load_data` alone
is all-or-nothing — one real load value (the first BJJ log) was enough to
flip it `True` and render the full charts with zero caveat, even though
`training_load` coverage is still ~2.5 months stale for everything else
(Francisco: "why don't my bike rides show up" + "I don't know what this
means"). Now also reports `is_stale`/`days_stale`, via the same
`load_metrics.load_staleness()` the persisted `derived_daily` rows already
used — this LIVE page gets the identical staleness read, not a second,
un-synced copy of the threshold.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from health_os.metrics import load as load_metrics


def _fetch_load_inputs(
    conn: sqlite3.Connection, bjj_calibration_factor: float
) -> list[tuple[str, float]]:
    activity_loads = [
        (r["local_date"], r["training_load"])
        for r in conn.execute(
            "SELECT local_date, training_load FROM activities WHERE training_load IS NOT NULL"
        ).fetchall()
    ]
    bjj_loads = [
        (r["date"], r["computed_load"])
        for r in conn.execute(
            "SELECT date, computed_load FROM bjj_sessions WHERE computed_load IS NOT NULL"
        ).fetchall()
    ]
    return load_metrics.build_daily_load_series(
        activity_loads, bjj_loads, bjj_calibration_factor=bjj_calibration_factor
    )


def _load_by_sport(conn: sqlite3.Connection, bjj_calibration_factor: float) -> list[dict[str, Any]]:
    """Real bug fixed 2026-08-30: this only ever read `activities.
    training_load`, so a real, recently-logged BJJ session that clearly
    moved the CTL/ATL/TSB chart and the weekly-load stat above it (both of
    which DO include `bjj_sessions.computed_load` via
    `build_daily_load_series()`) never showed up here at all — the two
    numbers on the same page silently disagreed about what "load" included.
    BJJ rows are now unioned in under `sport="bjj"`, scaled by the same
    calibration factor the CTL/ATL series already uses, so this chart and
    the summary stats above it are counting the same thing.
    """
    rows = conn.execute(
        "SELECT local_date, COALESCE(sport, 'unknown') AS sport, SUM(training_load) AS total "
        "FROM activities WHERE training_load IS NOT NULL "
        "GROUP BY local_date, COALESCE(sport, 'unknown') ORDER BY local_date"
    ).fetchall()
    by_sport = [{"date": r["local_date"], "sport": r["sport"], "load": r["total"]} for r in rows]

    bjj_rows = conn.execute(
        "SELECT date, SUM(computed_load) AS total FROM bjj_sessions "
        "WHERE computed_load IS NOT NULL GROUP BY date ORDER BY date"
    ).fetchall()
    by_sport += [
        {"date": r["date"], "sport": "bjj", "load": r["total"] * bjj_calibration_factor}
        for r in bjj_rows
    ]
    return sorted(by_sport, key=lambda r: r["date"])


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
    convention as `coach.briefing.compute_daily_plan()` — and is what
    `is_stale`/`days_stale` are measured against.
    """
    bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
    daily_load_series = _fetch_load_inputs(conn, bjj_cal)

    payload: dict[str, Any] = {
        "has_load_data": bool(daily_load_series),
        "is_stale": False,
        "days_stale": 0,
        "ctl_atl_tsb": [],
        "tsb_zscore": None,
        "monotony_strain": None,
        "load_by_sport": _load_by_sport(conn, bjj_cal),
        "calisthenics": _recent_calisthenics(conn),
    }

    if daily_load_series:
        is_stale, days_stale = load_metrics.load_staleness(daily_load_series[-1][0], as_of_date)
        payload["is_stale"] = is_stale
        payload["days_stale"] = days_stale

        ctl_atl_tsb = load_metrics.compute_ctl_atl(daily_load_series)
        payload["ctl_atl_tsb"] = [
            {"date": d, "ctl": ctl, "atl": atl, "tsb": tsb} for d, ctl, atl, tsb in ctl_atl_tsb
        ]
        tsb_series = [(d, tsb) for d, _ctl, _atl, tsb in ctl_atl_tsb]
        payload["tsb_zscore"] = load_metrics.compute_tsb_zscore(tsb_series)
        payload["monotony_strain"] = load_metrics.compute_monotony_strain(daily_load_series)

    return payload
