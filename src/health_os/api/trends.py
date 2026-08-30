"""Assembles the Trends page's payload — weight/HRV/RHR/sleep-stage series
over a selectable trailing window. Mirrors `dashboard/views/trends.py`.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

ALLOWED_WINDOW_DAYS = (30, 90, 365)
DEFAULT_SMOOTH_SPAN_DAYS = 7

_TIME_SERIES_COLUMNS = {
    "weight_kg": "Weight",
    "hrv_overnight_ms": "HRV (overnight)",
    "resting_hr": "Resting heart rate",
}
_READINESS_METRIC_NAME = "readiness_score"
_SLEEP_STAGE_COLUMNS = {
    "sleep_deep_min": "Deep",
    "sleep_light_min": "Light",
    "sleep_rem_min": "REM",
    "sleep_awake_min": "Awake",
}


def _smooth(observations: list[tuple[str, float]], span_days: int = DEFAULT_SMOOTH_SPAN_DAYS):
    """Same recursive-EWMA math as `dashboard/data.py: smooth_for_display()`
    -- kept as its own small copy here rather than importing from
    `dashboard/` (which pulls in Streamlit at module level), for the exact
    "no analytical claims of its own, purely for chart smoothing" reasoning
    that function's own docstring already gives.
    """
    if not observations:
        return []
    alpha = 2.0 / (span_days + 1)
    result: list[tuple[str, float]] = []
    ewma: float | None = None
    for day, value in observations:
        ewma = value if ewma is None else alpha * value + (1 - alpha) * ewma
        result.append((day, ewma))
    return result


def build_trends_payload(conn: sqlite3.Connection, window_days: int) -> dict[str, Any]:
    """Everything the Trends page needs for one window, as one JSON-ready
    dict. `window_days` should be one of `ALLOWED_WINDOW_DAYS` -- the caller
    (the FastAPI route) validates that, this function just uses whatever
    it's given.
    """
    max_row = conn.execute("SELECT MAX(date) AS d FROM daily_metrics").fetchone()
    if max_row["d"] is None:
        return {
            "window_days": window_days,
            "series": {},
            "sleep_stages": [],
            "readiness": {
                "label": "Readiness score",
                "raw": [],
                "smoothed": [],
                "coverage_summary": {},
            },
        }

    cutoff = (date.fromisoformat(max_row["d"]) - timedelta(days=window_days - 1)).isoformat()

    series: dict[str, Any] = {}
    for column, label in _TIME_SERIES_COLUMNS.items():
        rows = conn.execute(
            f"SELECT date, {column} AS v FROM daily_metrics "  # noqa: S608
            f"WHERE {column} IS NOT NULL AND date >= ? ORDER BY date",
            (cutoff,),
        ).fetchall()
        obs = [(r["date"], r["v"]) for r in rows]
        series[column] = {
            "label": label,
            "raw": [{"date": d, "value": v} for d, v in obs],
            "smoothed": [{"date": d, "value": v} for d, v in _smooth(obs)],
        }

    stage_rows = conn.execute(
        "SELECT date, sleep_deep_min, sleep_light_min, sleep_rem_min, sleep_awake_min "
        "FROM daily_metrics WHERE date >= ? "
        "AND (sleep_deep_min IS NOT NULL OR sleep_light_min IS NOT NULL "
        "OR sleep_rem_min IS NOT NULL OR sleep_awake_min IS NOT NULL) "
        "ORDER BY date",
        (cutoff,),
    ).fetchall()
    sleep_stages = [
        {
            "date": r["date"],
            **{col: r[col] for col in _SLEEP_STAGE_COLUMNS if r[col] is not None},
        }
        for r in stage_rows
    ]

    readiness = _build_readiness_history(conn, cutoff)

    return {
        "window_days": window_days,
        "series": series,
        "sleep_stages": sleep_stages,
        "readiness": readiness,
    }


def _build_readiness_history(conn: sqlite3.Connection, cutoff: str) -> dict[str, Any]:
    """Readiness score over time, straight from `derived_daily` — real
    historical tracking of the composite itself, not just its inputs, now
    that it's actually persisted per date (added 2026-08-28) rather than
    only ever computed live for "today." Built 2026-08-30 after Francisco
    asked for this directly.

    `derived_daily` is a long/tall table (one row per (date, metric_name)),
    unlike `daily_metrics`'s wide columns, hence its own small query rather
    than reusing `_TIME_SERIES_COLUMNS`'s loop.

    Confidence is never hidden or averaged away (design principle 6) — most
    days will read "partial" (only the subjective/Hooper component is
    typically missing) rather than invented as "full"; `coverage_summary`
    reports the real count of each confidence level actually present in
    this window so a reader isn't left guessing how much of the chart to
    trust.
    """
    rows = conn.execute(
        "SELECT date, value, confidence, n_days FROM derived_daily "
        "WHERE metric_name = ? AND date >= ? AND value IS NOT NULL ORDER BY date",
        (_READINESS_METRIC_NAME, cutoff),
    ).fetchall()
    obs = [(r["date"], r["value"]) for r in rows]

    coverage_summary: dict[str, int] = {}
    for r in rows:
        key = r["confidence"] or "unknown"
        coverage_summary[key] = coverage_summary.get(key, 0) + 1

    return {
        "label": "Readiness score",
        "raw": [
            {"date": r["date"], "value": r["value"], "confidence": r["confidence"]} for r in rows
        ],
        "smoothed": [{"date": d, "value": v} for d, v in _smooth(obs)],
        "coverage_summary": coverage_summary,
    }
