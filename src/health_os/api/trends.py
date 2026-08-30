"""Assembles the Trends page's payload — weight/HRV/RHR/sleep-stage series
over a selectable trailing window, plus plain-language insights. Mirrors
`dashboard/views/trends.py` for the charts.

**Insights added 2026-08-30** (Francisco: "you need to tell me things you
see in trends from the data... no fluff no acronyms"): `insights` is a
short list of plain-English takeaways — "you're sleeping great," "you're
losing weight," etc. — built by `metrics/insights.py` from the SAME
baseline/trend computations that already power other pages (HRV/RHR
baselines, the weight OLS trend, the correlation engine), not a new,
separately-computed set of numbers. Always includes weight/sleep/HRV/RHR
(even as an honest "not enough data yet" when that's the real state) plus
zero or more correlation findings, only when a real, statistically
confirmed one exists.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from health_os.metrics import baselines, body_comp, insights
from health_os.metrics.correlations import build_daily_metrics_correlation_panel

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


def _trailing_week_avg(
    observations: list[tuple[str, float]], as_of: str, weeks_back: int
) -> float | None:
    """Plain average of `observations` over the 7-day window ending
    `weeks_back` weeks before `as_of` (0 = the week ending on `as_of`
    itself). `None` if that window has no real readings at all.
    """
    end = date.fromisoformat(as_of) - timedelta(days=7 * weeks_back)
    start = end - timedelta(days=6)
    vals = [v for d, v in observations if start.isoformat() <= d <= end.isoformat()]
    return sum(vals) / len(vals) if vals else None


def _build_insights(conn: sqlite3.Connection, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Uses the FULL available history for every input (never windowed by
    the 30/90/365 selector) — same reasoning `correlations.py` already uses:
    more real history only helps these, never hurts.
    """
    weight_rows = conn.execute(
        "SELECT date, weight_kg FROM daily_metrics WHERE weight_kg IS NOT NULL ORDER BY date"
    ).fetchall()
    weight_obs = [(r["date"], r["weight_kg"]) for r in weight_rows]

    sleep_rows = conn.execute(
        "SELECT date, sleep_total_min FROM daily_metrics "
        "WHERE sleep_total_min IS NOT NULL ORDER BY date"
    ).fetchall()
    sleep_obs = [(r["date"], r["sleep_total_min"]) for r in sleep_rows]

    hrv_rows = conn.execute(
        "SELECT date, hrv_overnight_ms FROM daily_metrics "
        "WHERE hrv_overnight_ms IS NOT NULL ORDER BY date"
    ).fetchall()
    hrv_obs = [(r["date"], r["hrv_overnight_ms"]) for r in hrv_rows]

    rhr_rows = conn.execute(
        "SELECT date, resting_hr FROM daily_metrics WHERE resting_hr IS NOT NULL ORDER BY date"
    ).fetchall()
    rhr_obs = [(r["date"], r["resting_hr"]) for r in rhr_rows]

    result: list[dict[str, Any]] = []

    trend = body_comp.weight_trend_ols(weight_obs)
    comp_countdown = None
    if weight_obs:
        goal = config.get("goals", {}).get("primary")
        if goal is not None:
            ewma_series = body_comp.compute_weight_ewma(weight_obs)
            comp_countdown = body_comp.comp_countdown(
                current_weight_kg=ewma_series[-1][1],
                trend_slope_kg_per_week=trend["slope_kg_per_week"],
                comp_date=goal["date"],
                weight_limit_kg=goal["weight_division_kg"],
                today=weight_obs[-1][0],
            )
    result.append(insights.weight_insight(trend, comp_countdown))

    sleep_debt = baselines.compute_sleep_debt(sleep_obs)
    this_week_avg = last_week_avg = None
    if sleep_obs:
        as_of = sleep_obs[-1][0]
        this_week_avg = _trailing_week_avg(sleep_obs, as_of, 0)
        last_week_avg = _trailing_week_avg(sleep_obs, as_of, 1)
        if this_week_avg is not None:
            this_week_avg /= 60.0
        if last_week_avg is not None:
            last_week_avg /= 60.0
    result.append(insights.sleep_insight(sleep_debt, this_week_avg, last_week_avg))

    result.append(insights.hrv_insight(baselines.compute_hrv_baseline(hrv_obs)))
    result.append(insights.rhr_insight(baselines.compute_rhr_baseline(rhr_obs)))

    correlations = build_daily_metrics_correlation_panel(conn)
    for r in correlations:
        corr_insight = insights.correlation_insight(
            {
                "confidence": r.confidence,
                "rho": r.rho,
                "n": r.n,
                "x_name": r.x_name,
                "y_name": r.y_name,
                "description": r.description,
            }
        )
        if corr_insight is not None:
            result.append({"metric": "correlation", "tone": "info", **corr_insight})

    return result


def build_trends_payload(
    conn: sqlite3.Connection, window_days: int, config: dict[str, Any]
) -> dict[str, Any]:
    """Everything the Trends page needs for one window, as one JSON-ready
    dict. `window_days` should be one of `ALLOWED_WINDOW_DAYS` -- the caller
    (the FastAPI route) validates that, this function just uses whatever
    it's given. `insights` is unaffected by `window_days` (see
    `_build_insights()`'s own docstring).
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
            "insights": [],
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
        "insights": _build_insights(conn, config),
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
