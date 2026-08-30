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
from health_os.metrics import strain as strain_metrics

NIGGLE_LOOKBACK_DAYS = 7
BAND_HISTORY_DAYS = 3


def _rows_to_tuples(rows: list[sqlite3.Row], value_col: str) -> list[tuple[str, float]]:
    return [(r["date"], r[value_col]) for r in rows if r[value_col] is not None]


def _fetch_daily_metrics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM daily_metrics ORDER BY date").fetchall()


def _fetch_load_series(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> list[tuple[str, float]]:
    """Rebuilt 2026-08-30 to reuse `metrics.strain.build_activity_based_load_
    series()` -- the same TRIMP/Foster per-day computation the Training page
    and the Daily Strain ring use — instead of `activities.training_load`
    (Garmin/Strava's own, largely NULL, opaque-unit column). Without this,
    the `tsb_persistently_negative` structural trigger and `monotony_strain_
    flag()` below would keep reading a different, sparser picture of
    training load than what the Training page now shows, an inconsistency
    this project's own discipline treats as a real bug, not a cosmetic one
    (see api/training.py's 2026-08-30 rebuild for the original motivation).
    Already bounded to `<= as_of_date` internally (walks from the earliest
    real `resting_hr` date through `as_of_date`, never past it).
    """
    return strain_metrics.build_activity_based_load_series(conn, config, as_of_date)


def _readiness_result_as_of(
    daily_rows: list[sqlite3.Row],
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

    No longer takes a TSB series (ADR 0007 removed TSB from this composite
    entirely) — `tsb_series` in `compute_daily_plan()` is still computed and
    used, just for the separate `tsb_persistently_negative` structural flag,
    not fed in here anymore.
    """
    truncated = [r for r in daily_rows if r["date"] <= as_of_date]
    if not truncated:
        return {"score": None, "components": {}, "coverage": 0.0, "confidence": "insufficient_data"}

    hrv_obs = _rows_to_tuples(truncated, "hrv_overnight_ms")
    rhr_obs = _rows_to_tuples(truncated, "resting_hr")
    sleep_obs = _rows_to_tuples(truncated, "sleep_total_min")
    sleep_quality_obs = _rows_to_tuples(truncated, "sleep_score")
    hrv_result = baselines.compute_hrv_baseline(hrv_obs)
    rhr_result = baselines.compute_rhr_baseline(rhr_obs)
    sleep_debt_result = baselines.compute_sleep_debt(sleep_obs)

    def _if_full(result: dict[str, Any], key: str) -> float | None:
        return result[key] if result.get("confidence") == "full" else None

    return readiness_metrics.compute_readiness_score(
        hrv_deviation_sd=_if_full(hrv_result, "deviation_sd"),
        rhr_deviation_sd=_if_full(rhr_result, "deviation_sd"),
        last_night_sleep_hours=(sleep_obs[-1][1] / 60.0) if sleep_obs else None,
        sleep_debt_hours=sleep_debt_result["debt_hours"]
        if sleep_debt_result["confidence"] != "insufficient_data"
        else None,
        # Garmin's own sleep_score -- factors in REM/deep/restlessness/timing,
        # something the duration+debt math above never looked at on its own
        # (real gap Francisco found 2026-08-30: our score read 97 the same
        # night Garmin's read 74 "Fair" for low REM). Same "last element ==
        # as_of_date" convention already used for last_night_sleep_hours above.
        sleep_quality_score=sleep_quality_obs[-1][1] if sleep_quality_obs else None,
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
    daily_load_series = _fetch_load_series(conn, config, today)
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
            "subjective": config["readiness_score"]["weight_subjective"],
        }
    )

    today_d = date.fromisoformat(today)
    readiness_results = [
        _readiness_result_as_of(
            daily_rows,
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
    # A hand-planned taper day (comp_prep.blocks[].daily_schedule) overrides
    # the generic weekly pattern entirely when one exists for `today` -- see
    # rules.taper_day_override()'s own docstring for why this real gap
    # existed until 2026-08-30 (the schedule was in config, nothing read it).
    taper_override = rules.taper_day_override(config, today)
    sessions_today = (
        [taper_override] if taper_override else rules.scheduled_sessions_for(config, weekday_name)
    )
    downgrade = rules.should_downgrade_to_rest(band_history)

    sessions_with_guidance = []
    for session in sessions_today:
        if session.get("type") == "taper":
            # Already has label/instruction from taper_day_override() --
            # authoritative, not readiness-band-modulated (see that
            # function's docstring for why layering a second reduction on
            # top would double-discount an already-reduced week).
            sessions_with_guidance.append(session)
            continue
        label = session["type"].replace("_", " ").title()
        if session.get("subtype"):
            label += f" ({session['subtype'].replace('_', ' ')})"
        instruction = rules.session_guidance(session, band, recent_neck_niggle=recent_neck_niggle)
        sessions_with_guidance.append({**session, "label": label, "instruction": instruction})

    hrv_obs_full = _rows_to_tuples(daily_rows, "hrv_overnight_ms")
    rhr_obs_full = _rows_to_tuples(daily_rows, "resting_hr")
    rhr_result_full = baselines.compute_rhr_baseline(rhr_obs_full)
    sleep_debt_result_full = baselines.compute_sleep_debt(
        _rows_to_tuples(daily_rows, "sleep_total_min")
    )
    structural_flags = {
        "downgrade_to_rest": downgrade,
        "hrv_sustained_low": rules.hrv_sustained_low(hrv_obs_full),
        "tsb_persistently_negative": rules.tsb_persistently_negative(tsb_series),
        "monotony_strain": rules.monotony_strain_flag(daily_load_series),
    }

    taper = rules.taper_status(config, today)
    deload_config = config.get("deload", {})
    deload = rules.should_deload(
        hrv_deviation=rules.hrv_sustained_deviation(
            hrv_obs_full, window_days=deload_config.get("hrv_sustained_deviation_days", 6)
        ),
        rhr_sustained_rise=bool(rhr_result_full.get("sustained_rise_flag")),
        sleep_debt_elevated=rules.sleep_debt_elevated(
            sleep_debt_result_full.get("debt_hours")
            if sleep_debt_result_full.get("confidence") != "insufficient_data"
            else None,
            threshold_hours=deload_config.get("sleep_debt_threshold_hours", 7.0),
        ),
        hooper_sustained_high=rules.hooper_sustained_high(
            hooper_by_date,
            today,
            window_days=deload_config.get("hooper_sustained_high_days", 3),
            threshold=deload_config.get("hooper_sustained_high_threshold", 22.0),
        ),
        tsb_persistently_negative=structural_flags["tsb_persistently_negative"],
        markers_required=deload_config.get("markers_required", 2),
    )

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
        "taper": taper,
        "deload": deload,
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

    taper = plan["taper"]
    if taper["active"]:
        lines.append(f"Taper week — {taper['days_to_competition']} day(s) to competition.")
    elif 0 <= taper["days_to_competition"] <= 21:
        lines.append(f"{taper['days_to_competition']} day(s) to competition.")

    lines.append(f"Readiness: {plan['band'].upper()}")

    if not plan["sessions"]:
        lines.append("Nothing scheduled today.")
    else:
        for session in plan["sessions"]:
            lines.append(f"  {session['label']}: {session['instruction']}")
        if plan["structural_flags"]["downgrade_to_rest"]:
            lines.append(
                "  ⚠ Your readiness has been low for several days in a row — worth cutting "
                "back further today than the guidance above already suggests."
            )

    flags = plan["structural_flags"]
    if flags["hrv_sustained_low"]:
        lines.append(
            "  ⚠ Your HRV has been below your normal range for 3 days straight — "
            "a sign your body could use more recovery."
        )
    if flags["tsb_persistently_negative"]:
        lines.append(
            "  ⚠ You've been carrying fatigue for over 4 days without a real freshness rebound."
        )
    if flags["monotony_strain"]:
        lines.append(
            "  ⚠ This week's training has been both hard and repetitive — a combination "
            "linked to higher burnout/injury risk. Worth an easier day."
        )

    deload = plan["deload"]
    if deload["recommended"]:
        deload_config = config.get("deload", {})
        duration = deload_config.get("duration_days", 6)
        volume_pct = deload_config.get("volume_reduction_pct", 40)
        fired = ", ".join(m.replace("_", " ") for m in deload["markers_fired"])
        lines.append("")
        lines.append(
            f"⚠ DELOAD RECOMMENDED — {len(deload['markers_fired'])} fatigue markers fired "
            f"({fired}). Suggest ~{duration} days at ~{volume_pct}% less volume, intensity "
            "capped, prefer reduced load over full rest."
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
