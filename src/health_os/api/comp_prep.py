"""Assembles the Comp Prep page's payload — weight trajectory vs. the
required path to the division limit, plus a projected-trend band. Mirrors
`dashboard/views/comp_prep.py`'s exact computation.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from health_os.metrics import body_comp


def build_comp_prep_payload(conn: sqlite3.Connection, config: dict[str, Any]) -> dict[str, Any]:
    """Everything the Comp Prep page needs, as one JSON-ready dict."""
    goal = config["goals"]["primary"]
    comp_date = goal["date"]
    weight_limit_kg = goal["weight_division_kg"]

    weight_rows = conn.execute(
        "SELECT date, weight_kg FROM daily_metrics WHERE weight_kg IS NOT NULL ORDER BY date"
    ).fetchall()
    weight_obs = [(r["date"], r["weight_kg"]) for r in weight_rows]

    if not weight_obs:
        return {
            "goal": {"name": goal["name"], "date": comp_date, "weight_limit_kg": weight_limit_kg},
            "has_weight_data": False,
        }

    today = weight_obs[-1][0]
    ewma_series = body_comp.compute_weight_ewma(weight_obs)
    trend = body_comp.weight_trend_ols(weight_obs)
    countdown = body_comp.comp_countdown(
        current_weight_kg=ewma_series[-1][1],
        trend_slope_kg_per_week=trend["slope_kg_per_week"],
        comp_date=comp_date,
        weight_limit_kg=weight_limit_kg,
        today=today,
    )

    comp_d = date.fromisoformat(comp_date)
    today_d = date.fromisoformat(today)
    n_weeks = max(int((comp_d - today_d).days / 7), 0) + 1
    projection_dates = [(today_d + timedelta(weeks=i)).isoformat() for i in range(n_weeks + 1)]
    current = countdown["current_weight_kg"]

    required_path = [
        {
            "date": projection_dates[i],
            "value": current - (current - weight_limit_kg) * (i / max(n_weeks, 1)),
        }
        for i in range(n_weeks + 1)
    ]

    projection = None
    if trend["confidence"] != "insufficient_data":
        slope = trend["slope_kg_per_week"]
        ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
        projection = {
            "mid": [
                {"date": projection_dates[i], "value": current + slope * i}
                for i in range(n_weeks + 1)
            ],
            "ci_low": [
                {"date": projection_dates[i], "value": current + ci_low * i}
                for i in range(n_weeks + 1)
            ],
            "ci_high": [
                {"date": projection_dates[i], "value": current + ci_high * i}
                for i in range(n_weeks + 1)
            ],
        }

    return {
        "goal": {"name": goal["name"], "date": comp_date, "weight_limit_kg": weight_limit_kg},
        "has_weight_data": True,
        "countdown": countdown,
        "trend": trend,
        "weight_raw": [{"date": d, "value": w} for d, w in weight_obs],
        "weight_ewma": [{"date": d, "value": w} for d, w in ewma_series],
        "required_path": required_path,
        "projection": projection,
    }
