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
from health_os.metrics import strain as strain_metrics


def _format_hours_minutes(total_min: float | None) -> str | None:
    if total_min is None:
        return None
    hours, minutes = divmod(round(total_min), 60)
    return f"{hours}h{minutes:02d}m"


def _format_sleep_display(daily_row: Any) -> str | None:
    """Duration alone, plus Garmin's own sleep_score when present (the
    quality half now blended into the sleep component score too, see
    metrics/readiness.py) -- shows both real inputs a reader would need to
    understand the ring's number, not just one of them.
    """
    duration = _format_hours_minutes(daily_row["sleep_total_min"])
    if duration is None:
        return None
    if daily_row["sleep_score"] is not None:
        return f"{duration} · Garmin {daily_row['sleep_score']:.0f}"
    return duration


def _annotate_components_with_display(components: dict[str, Any], daily_row: Any) -> dict[str, Any]:
    """Attach a plain-language `display_raw` string (the actual sensor
    reading, not the abstracted 0-100 score or its internal SD-deviation/
    z-score representation) to each component, plus an `excluded` flag.

    Real bug found 2026-08-30: Francisco compared the dashboard's component
    rings ("HRV 47", "RHR 24") against his real Garmin app and reasonably
    read them as raw HRV ms / RHR bpm -- they were always the readiness
    sub-SCORE (0-100), never the raw reading, and the raw reading was never
    shown anywhere on this page at all. `excluded` covers the companion
    fix (config/athlete.yaml: weight_tsb temporarily 0.0) -- a component
    that's present but contributes zero weight needs to look visibly
    different from a real, counted low score, not just show "0" the same
    way a genuinely bad reading would.
    """
    display_raw = {
        "hrv": f"{daily_row['hrv_overnight_ms']:.0f}ms"
        if daily_row is not None and daily_row["hrv_overnight_ms"] is not None
        else None,
        "rhr": f"{daily_row['resting_hr']:.0f}bpm"
        if daily_row is not None and daily_row["resting_hr"] is not None
        else None,
        "sleep": _format_sleep_display(daily_row) if daily_row is not None else None,
    }
    annotated: dict[str, Any] = {}
    for key, comp in components.items():
        annotated[key] = {
            **comp,
            "display_raw": display_raw.get(key),
            "excluded": comp.get("weight_used", 1.0) == 0.0,
        }
    return annotated


def _strain_to_json(result: dict[str, Any]) -> dict[str, Any]:
    """`build_daily_strain()`'s components are `StrainComponent` dataclass
    instances -- not directly JSON-serializable, so converted here rather
    than at the metrics layer (which stays a plain Python return value,
    reusable outside an HTTP context, same separation as everywhere else
    in this project).
    """
    return {
        **result,
        "components": [
            {
                "source": c.source,
                "method": c.method,
                "raw_load": round(c.raw_load, 1),
                "description": c.description,
            }
            for c in result["components"]
        ],
    }


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

    strain_result = strain_metrics.build_daily_strain(conn, today, config)

    deload_config = config.get("deload", {})

    return {
        "date": today,
        "weekday_name": plan["weekday_name"],
        "strain": _strain_to_json(strain_result),
        "readiness": {
            "score": plan["score_result"]["score"],
            "band": plan["band"],
            "coverage": plan["score_result"]["coverage"],
            "confidence": plan["score_result"]["confidence"],
            "components": _annotate_components_with_display(
                plan["score_result"]["components"], daily_row
            ),
        },
        "sessions": plan["sessions"],
        "structural_flags": plan["structural_flags"],
        "taper": plan["taper"],
        "deload": {
            **plan["deload"],
            "duration_days": deload_config.get("duration_days", 6),
            "volume_reduction_pct": deload_config.get("volume_reduction_pct", 40),
        },
        "nutrition_focus": plan["nutrition_focus"],
        "trend_observation": plan["trend_observation"],
        "sleep": sleep,
        "weight": weight,
        "comp_countdown": comp_countdown,
    }
