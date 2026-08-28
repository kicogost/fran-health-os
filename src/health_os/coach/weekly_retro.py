"""Weekly retro (kickoff doc section 7, Phase 7): 7-day weight trend + CI,
sessions completed vs. planned, total load with TSB/monotony, sleep totals,
protein adherence rate, social-meal count, waist delta, proposed
calisthenics progression.

Same "assemble real data, never invent" discipline as `coach/briefing.py`:
every number here either comes from a real logged value or is explicitly
marked as insufficient data — never filled in with a guess.

Calisthenics session completion and progression are checked against
`calisthenics_sessions` (migration 0003, 2026-08-28) — this used to be an
honest, explicitly-flagged gap ("no logging mechanism exists"), closed once
Francisco asked directly how to track it. `dashboard/views/training.py`'s
older gap note is now stale for the same reason.

"Social-meal count vs. weight trend" is reported as two side-by-side facts,
not a computed correlation — the kickoff doc's own Correlation engine (
Spearman rho with n/p) is a separate, explicitly-deferred Phase 7 piece that
needs 90 days of data this account doesn't have yet (see CLAUDE.md). Two raw
numbers next to each other for a human to eyeball is not the same claim as a
statistical correlation, and this module doesn't pretend otherwise.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from health_os.coach import rules
from health_os.metrics import body_comp
from health_os.metrics import load as load_metrics

WEEK_DAYS = 7
WAIST_LOOKBACK_DAYS = 21  # enough slack to catch last week's + this week's Sunday measurement


def _rows_to_tuples(rows: list[sqlite3.Row], value_col: str) -> list[tuple[str, float]]:
    return [(r["date"], r[value_col]) for r in rows if r[value_col] is not None]


def _session_completion(
    conn: sqlite3.Connection, config: dict[str, Any], week_start: date, week_end: date
) -> list[dict[str, Any]]:
    """Scheduled vs. actually-logged, one entry per scheduled session in the
    trailing week. Calisthenics is checked against `calisthenics_sessions`
    (migration 0003) — this used to be marked "not trackable" (no logging
    mechanism existed at all), a real, documented gap closed 2026-08-28.
    """
    bjj_dates = {r["date"] for r in conn.execute("SELECT date FROM bjj_sessions").fetchall()}
    bike_dates = {
        r["local_date"]
        for r in conn.execute(
            "SELECT local_date FROM activities WHERE sport = 'cycling'"
        ).fetchall()
    }
    calisthenics_dates = {
        r["date"] for r in conn.execute("SELECT date FROM calisthenics_sessions").fetchall()
    }

    entries = []
    current = week_start
    while current <= week_end:
        weekday_name = current.strftime("%A").lower()
        for session in rules.scheduled_sessions_for(config, weekday_name):
            iso = current.isoformat()
            if session["type"] == "bjj":
                status = "completed" if iso in bjj_dates else "missed"
            elif session["type"] == "bike":
                status = "completed" if iso in bike_dates else "missed"
            elif session["type"] == "calisthenics":
                status = "completed" if iso in calisthenics_dates else "missed"
            else:  # rest
                status = "n/a"
            entries.append(
                {
                    "date": iso,
                    "type": session["type"],
                    "subtype": session.get("subtype"),
                    "status": status,
                }
            )
        current += timedelta(days=1)
    return entries


def compute_weekly_retro(
    conn: sqlite3.Connection, config: dict[str, Any], week_ending: str
) -> dict[str, Any]:
    """Everything the weekly retro needs, as structured data. `week_ending`
    is an explicit ISO date (the Sunday the retro covers, Europe/Madrid) —
    the trailing 7 days ending on and including that date.
    """
    week_end = date.fromisoformat(week_ending)
    week_start = week_end - timedelta(days=WEEK_DAYS - 1)
    week_start_iso, week_end_iso = week_start.isoformat(), week_end.isoformat()

    daily_rows = conn.execute(
        "SELECT * FROM daily_metrics WHERE date <= ? ORDER BY date", (week_end_iso,)
    ).fetchall()
    weight_obs = _rows_to_tuples(daily_rows, "weight_kg")
    weight_trend = body_comp.weight_trend_ols(weight_obs, window_days=WEEK_DAYS)

    week_sleep = [
        r["sleep_total_min"]
        for r in daily_rows
        if week_start_iso <= r["date"] <= week_end_iso and r["sleep_total_min"] is not None
    ]

    bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
    activity_loads = [
        (r["local_date"], r["training_load"])
        for r in conn.execute(
            "SELECT local_date, training_load FROM activities WHERE training_load IS NOT NULL "
            "AND local_date <= ?",
            (week_end_iso,),
        ).fetchall()
    ]
    bjj_loads = [
        (r["date"], r["computed_load"])
        for r in conn.execute(
            "SELECT date, computed_load FROM bjj_sessions WHERE computed_load IS NOT NULL "
            "AND date <= ?",
            (week_end_iso,),
        ).fetchall()
    ]
    daily_load_series = load_metrics.build_daily_load_series(
        activity_loads, bjj_loads, bjj_calibration_factor=bjj_cal
    )
    ctl_atl_tsb = load_metrics.compute_ctl_atl(daily_load_series)
    latest_tsb = ctl_atl_tsb[-1][3] if ctl_atl_tsb else None
    week_loads = [load for d, load in daily_load_series if week_start_iso <= d <= week_end_iso]
    monotony = load_metrics.compute_monotony_strain(
        [(d, load) for d, load in daily_load_series if d <= week_end_iso]
    )

    protein_rows = [
        r["protein_hit"]
        for r in conn.execute(
            "SELECT protein_hit FROM subjective_log WHERE date >= ? AND date <= ? "
            "AND protein_hit IS NOT NULL",
            (week_start_iso, week_end_iso),
        ).fetchall()
    ]
    protein_adherence = (
        (sum(1 for p in protein_rows if p) / len(protein_rows)) if protein_rows else None
    )

    social_meal_count = conn.execute(
        "SELECT COUNT(*) AS n FROM subjective_log WHERE date >= ? AND date <= ? "
        "AND social_meal = 1",
        (week_start_iso, week_end_iso),
    ).fetchone()["n"]

    waist_cutoff = (week_end - timedelta(days=WAIST_LOOKBACK_DAYS - 1)).isoformat()
    waist_rows = conn.execute(
        "SELECT date, value_cm FROM body_measurements WHERE measurement_type = 'waist' "
        "AND date >= ? AND date <= ? ORDER BY date",
        (waist_cutoff, week_end_iso),
    ).fetchall()
    waist_delta = None
    if len(waist_rows) >= 2:
        waist_delta = waist_rows[-1]["value_cm"] - waist_rows[-2]["value_cm"]

    calisthenics_rows = conn.execute(
        "SELECT date, session_type, session_rpe, exercises_json FROM calisthenics_sessions "
        "WHERE date >= ? AND date <= ? ORDER BY date",
        (week_start_iso, week_end_iso),
    ).fetchall()
    calisthenics_logs = [
        {
            "date": r["date"],
            "session_type": r["session_type"],
            "session_rpe": r["session_rpe"],
            "exercises": json.loads(r["exercises_json"]) if r["exercises_json"] else None,
        }
        for r in calisthenics_rows
    ]

    return {
        "week_start": week_start_iso,
        "week_end": week_end_iso,
        "weight_trend": weight_trend,
        "sessions": _session_completion(conn, config, week_start, week_end),
        "total_load": sum(week_loads) if week_loads else None,
        "latest_tsb": latest_tsb,
        "monotony": monotony,
        "sleep_total_min_avg": (sum(week_sleep) / len(week_sleep)) if week_sleep else None,
        "sleep_nights_logged": len(week_sleep),
        "protein_adherence_rate": protein_adherence,
        "protein_days_logged": len(protein_rows),
        "social_meal_count": social_meal_count,
        "calisthenics_logs": calisthenics_logs,
        "waist_delta_cm": waist_delta,
        "waist_measurements_in_window": len(waist_rows),
    }


def format_weekly_retro(plan: dict[str, Any]) -> str:
    lines = [f"Weekly retro — {plan['week_start']} to {plan['week_end']}", ""]

    trend = plan["weight_trend"]
    if trend["confidence"] == "insufficient_data":
        lines.append("Weight trend (7d): insufficient data (needs 3+ weigh-ins this week).")
    else:
        lines.append(
            f"Weight trend (7d): {trend['slope_kg_per_week']:+.2f} kg/wk "
            f"(95% CI [{trend['ci_low_kg_per_week']:+.2f}, {trend['ci_high_kg_per_week']:+.2f}], "
            f"n={trend['n']})"
        )

    lines.append("")
    lines.append("Sessions:")
    for s in plan["sessions"]:
        label = s["type"].replace("_", " ").title()
        if s["subtype"]:
            label += f" ({s['subtype'].replace('_', ' ')})"
        status_text = {
            "completed": "✓ completed",
            "missed": "✗ missed",
            "n/a": "rest",
        }.get(s["status"], s["status"])
        lines.append(f"  {s['date']} {label}: {status_text}")

    lines.append("")
    if plan["total_load"] is not None:
        lines.append(f"Total load this week: {plan['total_load']:.0f}")
    if plan["latest_tsb"] is not None:
        lines.append(f"Latest TSB (freshness): {plan['latest_tsb']:+.1f}")
    mono = plan["monotony"]
    if mono["confidence"] == "full":
        flag = " ⚠ high" if mono["flag_high_monotony"] else ""
        lines.append(f"Monotony: {mono['monotony']:.2f}{flag}, strain {mono['strain']:.0f}")

    lines.append("")
    if plan["sleep_nights_logged"] > 0:
        lines.append(
            f"Sleep: {plan['sleep_total_min_avg'] / 60:.1f}h avg "
            f"({plan['sleep_nights_logged']}/{WEEK_DAYS} nights logged)"
        )
    else:
        lines.append("Sleep: no nights logged this week.")

    if plan["protein_adherence_rate"] is not None:
        lines.append(
            f"Protein adherence: {plan['protein_adherence_rate'] * 100:.0f}% "
            f"({plan['protein_days_logged']}/{WEEK_DAYS} days logged)"
        )
    else:
        lines.append("Protein adherence: not logged this week.")

    lines.append(f"Social meals this week: {plan['social_meal_count']}")

    lines.append("")
    if plan["waist_delta_cm"] is not None:
        lines.append(f"Waist delta: {plan['waist_delta_cm']:+.1f} cm since last measurement")
    else:
        lines.append("Waist delta: insufficient data (needs 2+ measurements).")

    lines.append("")
    lines.append("Calisthenics:")
    if not plan["calisthenics_logs"]:
        lines.append("  Nothing logged this week.")
    else:
        for log in plan["calisthenics_logs"]:
            header = f"  {log['date']} {log['session_type']}"
            if log["session_rpe"] is not None:
                header += f" (RPE {log['session_rpe']})"
            lines.append(header)
            if not log["exercises"]:
                lines.append("    (no per-exercise detail logged)")
            else:
                for ex in log["exercises"]:
                    detail = f"    {ex['exercise']}: {ex['sets']}x{ex['reps']}"
                    if ex.get("added_weight_kg"):
                        detail += f" @ +{ex['added_weight_kg']}kg"
                    lines.append(detail)
        lines.append(
            "  (proposing a progression — e.g. add a rep or a kg next time — needs "
            "comparing against a prior week's log for the same exercise; not computed "
            "yet, this just shows what was actually logged)"
        )

    return "\n".join(lines)
