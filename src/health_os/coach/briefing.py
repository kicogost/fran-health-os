"""Daily briefing generator (kickoff doc section 7, Phase 7).

Assembles real data from the DB and `config/athlete.yaml`, computes today's
readiness the same way `metrics/readiness.py` always has, and calls
`coach/rules.py` for every decision. `compute_daily_plan()` is the one real
computation — both `scripts/briefing.py` (CLI) and the dashboard's Today page
(`dashboard/views/today.py`) call it directly, so there is exactly one
version of "today's actual coaching decision" in this codebase, not a real
one here and a separate simplified preview in `dashboard/` (that preview
existed only until this module was built — see its own git history and
ADR 0005). `build_briefing()` is a thin text formatter over that same data
for the CLI. No dashboard import here (`sqlite3`/plain dicts only) — this
needs to run standalone without a Streamlit dependency; the dashboard is the
one importing this module, never the other way around.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from health_os.coach import rules
from health_os.metrics import baselines, body_comp
from health_os.metrics import load as load_metrics
from health_os.metrics import readiness as readiness_metrics

NIGGLE_LOOKBACK_DAYS = 7
BAND_HISTORY_DAYS = 3


def _rows_to_tuples(rows: list[sqlite3.Row], value_col: str) -> list[tuple[str, float]]:
    return [(r["date"], r[value_col]) for r in rows if r[value_col] is not None]


def _fetch_daily_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM daily_metrics ORDER BY date").fetchall()


def _fetch_load_series(
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


def _readiness_result_as_of(
    daily_rows: list[sqlite3.Row],
    tsb_series: list[tuple[str, float]],
    hooper_by_date: dict[str, float],
    weights: dict[str, float],
    as_of_date: str,
) -> dict[str, Any]:
    """Recomputes the FULL `compute_readiness_score()` result as of
    `as_of_date` by truncating every observation series to that date — the
    same component-assembly `views/today.py` used to do inline for "today",
    generalized to an arbitrary historical date so `should_downgrade_to_rest()`
    can see a real trailing band history instead of just today's single
    score. Returns the full result (not just the band) so callers wanting
    today's component breakdown (e.g. the dashboard's ring gauges) don't need
    a second, separate computation.
    """
    truncated = [r for r in daily_rows if r["date"] <= as_of_date]
    if not truncated:
        return {"score": None, "components": {}, "coverage": 0.0, "confidence": "insufficient_data"}

    hrv_obs = _rows_to_tuples(truncated, "hrv_overnight_ms")
    rhr_obs = _rows_to_tuples(truncated, "resting_hr")
    sleep_obs = _rows_to_tuples(truncated, "sleep_total_min")
    hrv_result = baselines.compute_hrv_baseline(hrv_obs)
    rhr_result = baselines.compute_rhr_baseline(rhr_obs)
    sleep_debt_result = baselines.compute_sleep_debt(sleep_obs)
    tsb_as_of = [(d, tsb) for d, tsb in tsb_series if d <= as_of_date]
    tsb_zscore_result = load_metrics.compute_tsb_zscore(tsb_as_of)

    def _if_full(result: dict[str, Any], key: str) -> float | None:
        return result[key] if result.get("confidence") == "full" else None

    return readiness_metrics.compute_readiness_score(
        hrv_deviation_sd=_if_full(hrv_result, "deviation_sd"),
        rhr_deviation_sd=_if_full(rhr_result, "deviation_sd"),
        last_night_sleep_hours=(sleep_obs[-1][1] / 60.0) if sleep_obs else None,
        sleep_debt_hours=sleep_debt_result["debt_hours"]
        if sleep_debt_result["confidence"] != "insufficient_data"
        else None,
        tsb_z_score=_if_full(tsb_zscore_result, "z_score"),
        hooper_index=hooper_by_date.get(as_of_date),
        weights=weights,
    )


def compute_daily_plan(
    conn: sqlite3.Connection, config: dict[str, Any], today: str
) -> dict[str, Any]:
    """Everything `build_briefing()` needs, as structured data rather than
    formatted text — the single real computation both `scripts/briefing.py`
    (CLI) and the dashboard's Today page call, so there is exactly one
    version of "today's actual coaching decision" in this codebase, not a
    real one here and a simplified preview duplicated in `dashboard/`.
    `today` is an explicit ISO date (Europe/Madrid) rather than read from the
    clock here, so this is testable without mocking `datetime.now()` — and,
    since `scripts/briefing.py --date <past date>` is an explicitly supported
    backtest path, `today` can be any historical date, not just "now."
    Every series fetched below is truncated to `<= today` right after
    fetching, for exactly that reason: a real bug (found 2026-08-28) had
    `daily_rows`/`daily_load_series`/`tsb_series` fetched unbounded, so
    calling this with a past `today` while the DB already has LATER rows
    (the normal state of affairs days after the fact) could leak future data
    into the structural flags below (`hrv_sustained_low`,
    `tsb_persistently_negative`, `monotony_strain`) and into
    `_notable_trend_observation()`, even though the readiness SCORE itself
    was already correctly bounded via `_readiness_result_as_of()`'s own
    per-day truncation — an internally inconsistent result for one `as_of`
    date. Truncating once here, immediately after each fetch, means every
    downstream consumer in this function only ever sees data through `today`.
    """
    daily_rows = [r for r in _fetch_daily_metrics(conn) if r["date"] <= today]
    bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
    daily_load_series = [(d, load) for d, load in _fetch_load_series(conn, bjj_cal) if d <= today]
    tsb_series = [
        (d, tsb) for d, _ctl, _atl, tsb in load_metrics.compute_ctl_atl(daily_load_series)
    ]
    hooper_by_date = {
        r["date"]: r["hooper_index"]
        for r in conn.execute(
            "SELECT date, hooper_index FROM subjective_log WHERE hooper_index IS NOT NULL"
        ).fetchall()
    }
    weights = readiness_metrics.DEFAULT_READINESS_WEIGHTS.copy()
    weights.update(
        {
            "hrv": config["readiness_score"]["weight_hrv"],
            "sleep": config["readiness_score"]["weight_sleep"],
            "rhr": config["readiness_score"]["weight_rhr"],
            "tsb": config["readiness_score"]["weight_tsb"],
            "subjective": config["readiness_score"]["weight_subjective"],
        }
    )

    today_d = date.fromisoformat(today)
    readiness_results = [
        _readiness_result_as_of(
            daily_rows,
            tsb_series,
            hooper_by_date,
            weights,
            (today_d - timedelta(days=i)).isoformat(),
        )
        for i in range(BAND_HISTORY_DAYS - 1, -1, -1)
    ]
    band_history = [rules.classify_readiness_band(r["score"]) for r in readiness_results]
    band = band_history[-1]
    score_result = readiness_results[-1]

    niggle_cutoff = (today_d - timedelta(days=NIGGLE_LOOKBACK_DAYS - 1)).isoformat()
    niggle_texts = [
        r["niggles"]
        for r in conn.execute(
            "SELECT niggles FROM subjective_log WHERE date >= ? AND niggles IS NOT NULL",
            (niggle_cutoff,),
        ).fetchall()
    ] + [
        r["niggles"]
        for r in conn.execute(
            "SELECT niggles FROM bjj_sessions WHERE date >= ? AND niggles IS NOT NULL",
            (niggle_cutoff,),
        ).fetchall()
    ]
    recent_neck_niggle = rules.has_recent_neck_niggle(niggle_texts)

    weekday_name = today_d.strftime("%A").lower()
    sessions_today = rules.scheduled_sessions_for(config, weekday_name)
    downgrade = rules.should_downgrade_to_rest(band_history)

    sessions_with_guidance = []
    for session in sessions_today:
        label = session["type"].replace("_", " ").title()
        if session.get("subtype"):
            label += f" ({session['subtype'].replace('_', ' ')})"
        instruction = rules.session_guidance(session, band, recent_neck_niggle=recent_neck_niggle)
        sessions_with_guidance.append({**session, "label": label, "instruction": instruction})

    hrv_obs_full = _rows_to_tuples(daily_rows, "hrv_overnight_ms")
    structural_flags = {
        "downgrade_to_rest": downgrade,
        "hrv_sustained_low": rules.hrv_sustained_low(hrv_obs_full),
        "tsb_persistently_negative": rules.tsb_persistently_negative(tsb_series),
        "monotony_strain": rules.monotony_strain_flag(daily_load_series),
    }

    yesterday = (today_d - timedelta(days=1)).isoformat()
    yesterday_row = conn.execute(
        "SELECT social_meal FROM subjective_log WHERE date = ?", (yesterday,)
    ).fetchone()
    yesterday_social_meal = bool(yesterday_row["social_meal"]) if yesterday_row else None

    return {
        "today": today,
        "weekday_name": weekday_name,
        "score_result": score_result,
        "band": band,
        "band_history": band_history,
        "recent_neck_niggle": recent_neck_niggle,
        "sessions": sessions_with_guidance,
        "structural_flags": structural_flags,
        "nutrition_focus": rules.nutrition_focus(
            config, yesterday_social_meal=yesterday_social_meal
        ),
        "trend_observation": _notable_trend_observation(daily_rows, config, today),
    }


def build_briefing(conn: sqlite3.Connection, config: dict[str, Any], today: str) -> str:
    """The full daily briefing text: today's session(s) adjusted for
    readiness, one nutrition focus, one trend observation only if notable.
    Thin formatter over `compute_daily_plan()` — see that function for the
    actual computation.
    """
    plan = compute_daily_plan(conn, config, today)
    lines = [f"Health OS briefing — {plan['today']} ({plan['weekday_name'].capitalize()})", ""]
    lines.append(f"Readiness: {plan['band'].upper()}")

    if not plan["sessions"]:
        lines.append("Nothing scheduled today.")
    else:
        for session in plan["sessions"]:
            lines.append(f"  {session['label']}: {session['instruction']}")
        if plan["structural_flags"]["downgrade_to_rest"]:
            lines.append(
                "  ⚠ Structural: 2+ consecutive red days or 3 amber days in a row — "
                "consider downgrading today's session further, not just per-band guidance above."
            )

    flags = plan["structural_flags"]
    if flags["hrv_sustained_low"]:
        lines.append("  ⚠ Structural: HRV has sat >1 SD below baseline for 3 straight days.")
    if flags["tsb_persistently_negative"]:
        lines.append("  ⚠ Structural: TSB has been negative for 4+ straight days.")
    if flags["monotony_strain"]:
        lines.append(
            "  ⚠ Structural: high monotony this week with strain in the recent top quartile."
        )

    lines.append("")
    lines.append(f"Nutrition: {plan['nutrition_focus']}")

    if plan["trend_observation"]:
        lines.append("")
        lines.append(f"Trend: {plan['trend_observation']}")

    return "\n".join(lines)


def _notable_trend_observation(
    daily_rows: list[sqlite3.Row], config: dict[str, Any], today: str
) -> str | None:
    """One trend observation, only if genuinely notable — kickoff doc:
    "silence is valid, don't manufacture an insight daily." Checks a small,
    fixed priority list of real conditions; returns the first that fires, or
    `None` if none do (no line is added to the briefing in that case).
    """
    rhr_obs = _rows_to_tuples(daily_rows, "resting_hr")
    rhr_result = baselines.compute_rhr_baseline(rhr_obs)
    if rhr_result.get("sustained_rise_flag"):
        return "Resting HR has been sustained-elevated (>1 SD above baseline) for 3 straight days."

    weight_obs = _rows_to_tuples(daily_rows, "weight_kg")
    if weight_obs:
        trend = body_comp.weight_trend_ols(weight_obs)
        if trend["confidence"] == "full":
            ewma_series = body_comp.compute_weight_ewma(weight_obs)
            countdown = body_comp.comp_countdown(
                current_weight_kg=ewma_series[-1][1],
                trend_slope_kg_per_week=trend["slope_kg_per_week"],
                comp_date=config["goals"]["primary"]["date"],
                weight_limit_kg=config["goals"]["primary"]["weight_division_kg"],
                today=today,
            )
            if countdown["red_flag"]:
                return (
                    f"Comp weight countdown needs {countdown['required_kg_per_week']:.2f} kg/wk "
                    "— over the 0.7 kg/wk red line, a performance-risk pace, not just a diet one."
                )
    return None
