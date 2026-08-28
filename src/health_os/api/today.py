"""Assembles the Today page's full payload for the React frontend (ADR 0005)
— the same data `dashboard/views/today.py` shows, extracted into one pure,
JSON-ready function so the FastAPI route (`api/main.py`) is a thin wrapper,
not a second copy of this logic. Reuses `coach.briefing.compute_daily_plan()`
directly (the one real coaching computation, design principle 9) and
`metrics.body_comp` for weight/comp-countdown — exactly what the Streamlit
page already calls, no reinvention.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from health_os.coach import briefing
from health_os.metrics import body_comp


def build_today_payload(
    conn: sqlite3.Connection, config: dict[str, Any], today: str
) -> dict[str, Any]:
    """Everything the Today page needs, as one JSON-ready dict. `today` is
    an explicit ISO date (normally the latest date with a `daily_metrics`
    row — the caller resolves that, this stays a pure function of its
    inputs, same convention as `compute_daily_plan()` itself).
    """
    plan = briefing.compute_daily_plan(conn, config, today)

    daily_row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", (today,)).fetchone()
    sleep = None
    if daily_row is not None and daily_row["sleep_total_min"] is not None:
        sleep = {
            "total_min": daily_row["sleep_total_min"],
            "deep_min": daily_row["sleep_deep_min"],
            "light_min": daily_row["sleep_light_min"],
            "rem_min": daily_row["sleep_rem_min"],
            "awake_min": daily_row["sleep_awake_min"],
        }

    weight_rows = conn.execute(
        "SELECT date, weight_kg FROM daily_metrics "
        "WHERE weight_kg IS NOT NULL AND date <= ? ORDER BY date",
        (today,),
    ).fetchall()
    weight_obs = [(r["date"], r["weight_kg"]) for r in weight_rows]

    weight = None
    comp_countdown = None
    if weight_obs:
        ewma_series = body_comp.compute_weight_ewma(weight_obs)
        trend = body_comp.weight_trend_ols(weight_obs)
        weight = {
            "ewma_kg": ewma_series[-1][1],
            "latest_kg": weight_obs[-1][1],
            "latest_date": weight_obs[-1][0],
        }
        countdown = body_comp.comp_countdown(
            current_weight_kg=ewma_series[-1][1],
            trend_slope_kg_per_week=trend["slope_kg_per_week"],
            comp_date=config["goals"]["primary"]["date"],
            weight_limit_kg=config["goals"]["primary"]["weight_division_kg"],
            today=today,
        )
        comp_countdown = {
            "kg_remaining": countdown["kg_remaining"],
            "weeks_remaining": countdown["weeks_remaining"],
            "required_kg_per_week": countdown["required_kg_per_week"],
            "actual_kg_per_week": countdown["actual_kg_per_week"],
            "red_flag": countdown["red_flag"],
        }

    return {
        "date": today,
        "weekday_name": plan["weekday_name"],
        "readiness": {
            "score": plan["score_result"]["score"],
            "band": plan["band"],
            "coverage": plan["score_result"]["coverage"],
            "confidence": plan["score_result"]["confidence"],
            "components": plan["score_result"]["components"],
        },
        "sessions": plan["sessions"],
        "structural_flags": plan["structural_flags"],
        "nutrition_focus": plan["nutrition_focus"],
        "trend_observation": plan["trend_observation"],
        "sleep": sleep,
        "weight": weight,
        "comp_countdown": comp_countdown,
    }
