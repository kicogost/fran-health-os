"""Assembles the Training page's payload — CTL/ATL/TSB, monotony/strain,
load by day/sport, recent calisthenics sessions. Mirrors
`dashboard/views/training.py`, including its own honest "no training_load
data yet" state rather than an empty/misleading chart (see CLAUDE.md's
training-load build-out notes for why that's a real, current condition on
this account, not a bug).
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


def _load_by_sport(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT local_date, COALESCE(sport, 'unknown') AS sport, SUM(training_load) AS total "
        "FROM activities WHERE training_load IS NOT NULL "
        "GROUP BY local_date, COALESCE(sport, 'unknown') ORDER BY local_date"
    ).fetchall()
    return [{"date": r["local_date"], "sport": r["sport"], "load": r["total"]} for r in rows]


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


def build_training_payload(conn: sqlite3.Connection, config: dict[str, Any]) -> dict[str, Any]:
    """Everything the Training page needs, as one JSON-ready dict."""
    bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
    daily_load_series = _fetch_load_inputs(conn, bjj_cal)

    payload: dict[str, Any] = {
        "has_load_data": bool(daily_load_series),
        "ctl_atl_tsb": [],
        "tsb_zscore": None,
        "monotony_strain": None,
        "load_by_sport": _load_by_sport(conn),
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
