"""Persists the Phase 4 derived-metric suite into `derived_daily`
(migration 0001) — the one gap flagged repeatedly across this project's
build history: HRV/RHR baselines, sleep debt, CTL/ATL/TSB, monotony/strain,
weight trend, comp countdown, and the readiness score have all been
computable since 2026-08-28 (`metrics/baselines.py`, `metrics/load.py`,
`metrics/body_comp.py`, `metrics/readiness.py`), but nothing ever wrote a
single row to `derived_daily` — every number was recomputed live, on
demand, with no historical record. This module closes that gap.

Design principle 9 (traceability): every row stores not just `value` but
`confidence`, `n_days`, `window_days`, and an `inputs_json` payload with
enough of the underlying numbers that the value is explainable without
re-deriving it. Design principle 6 (never invent data): a metric that
can't be computed for a date (not enough history, no data at all) still
gets a row — `value=None`, `confidence="insufficient_data"` — rather than
being silently absent, so a gap in `derived_daily` for a real date always
means "the pipeline didn't run," never "there was nothing to compute."

**Every observation series fetched here is bounded to `<= as_of_date`
before use, deliberately** — the exact discipline `coach/briefing.py`
gained 2026-08-28 after a real future-data-leakage bug was found there
(see CLAUDE.md's "Deep review pass" entry). This module is built fresh
with that lesson already applied, not retrofitted.

**CTL/ATL/TSB honesty note**: `metrics.load.build_daily_load_series()`
only walks from the first to the LAST OBSERVED date in its inputs — it does
NOT extend to `as_of_date` with invented zero-load days if training/BJJ
logging has gone stale (a real, already-documented condition in this
project — CLAUDE.md's training-load build-out section). This module does
NOT paper over that by padding with assumed zeros (an untracked training
day is not the same as a genuine rest day, and inventing that distinction
away would be exactly the kind of false precision design principle 6 warns
against). Instead, when a series' last real date is more than
`STALE_LOAD_THRESHOLD_DAYS` before `as_of_date`, the affected rows carry
`confidence="stale"` and `inputs_json` records how many days stale, so a
dashboard reading these rows can't mistake a stale carried-forward number
for a fresh one. The same treatment applies to the weight/EWMA metrics for
the identical reason (a gap in weigh-ins isn't a gap in load, but the
principle — don't silently present old data as current — is the same).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from health_os.core import db
from health_os.core.models import DerivedMetric
from health_os.metrics import baselines, body_comp
from health_os.metrics import load as load_metrics
from health_os.metrics import readiness as readiness_metrics

STALE_LOAD_THRESHOLD_DAYS = 3  # matches sync.py's own trailing-window granularity


def _rows_to_tuples(rows: list[sqlite3.Row], value_col: str) -> list[tuple[str, float]]:
    return [(r["date"], r[value_col]) for r in rows if r[value_col] is not None]


def _fetch_daily_metrics(conn: sqlite3.Connection, as_of_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM daily_metrics WHERE date <= ? ORDER BY date", (as_of_date,)
    ).fetchall()


def _fetch_load_series(
    conn: sqlite3.Connection, bjj_calibration_factor: float, as_of_date: str
) -> list[tuple[str, float]]:
    activity_loads = [
        (r["local_date"], r["training_load"])
        for r in conn.execute(
            "SELECT local_date, training_load FROM activities "
            "WHERE training_load IS NOT NULL AND local_date <= ?",
            (as_of_date,),
        ).fetchall()
    ]
    bjj_loads = [
        (r["date"], r["computed_load"])
        for r in conn.execute(
            "SELECT date, computed_load FROM bjj_sessions "
            "WHERE computed_load IS NOT NULL AND date <= ?",
            (as_of_date,),
        ).fetchall()
    ]
    return load_metrics.build_daily_load_series(
        activity_loads, bjj_loads, bjj_calibration_factor=bjj_calibration_factor
    )


def _staleness(last_series_date: str | None, as_of_date: str) -> tuple[bool, int]:
    """`(is_stale, days_stale)` for a date-sorted series's last real date
    compared to `as_of_date` — see module docstring's CTL/ATL/TSB honesty
    note for why this isn't silently padded away instead.
    """
    if last_series_date is None:
        return False, 0
    days_stale = (date.fromisoformat(as_of_date) - date.fromisoformat(last_series_date)).days
    return days_stale >= STALE_LOAD_THRESHOLD_DAYS, days_stale


def _metric(
    as_of_date: str,
    metric_name: str,
    *,
    value: float | None,
    unit: str | None = None,
    window_days: int | None = None,
    n_days: int | None = None,
    confidence: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> DerivedMetric:
    return DerivedMetric(
        date=as_of_date,
        metric_name=metric_name,
        value=value,
        unit=unit,
        window_days=window_days,
        n_days=n_days,
        confidence=confidence,
        inputs=inputs,
    )


def _hrv_baseline_metric(daily_rows: list[sqlite3.Row], as_of_date: str) -> DerivedMetric:
    result = baselines.compute_hrv_baseline(_rows_to_tuples(daily_rows, "hrv_overnight_ms"))
    return _metric(
        as_of_date,
        "hrv_baseline",
        value=result.get("deviation_sd"),
        unit="sd",
        window_days=baselines.DEFAULT_BASELINE_WINDOW_DAYS,
        n_days=result.get("n_days"),
        confidence=result["confidence"],
        inputs={
            "status": result["status"],
            "baseline_method": result["baseline_method"],
            "value_ms": result["value"],
            "baseline_median_ms": result.get("baseline_median"),
            "baseline_sd_ms": result.get("baseline_sd"),
        },
    )


def _rhr_baseline_metric(daily_rows: list[sqlite3.Row], as_of_date: str) -> DerivedMetric:
    result = baselines.compute_rhr_baseline(_rows_to_tuples(daily_rows, "resting_hr"))
    # Unlike HRV, RHR baseline has no seed phase (its own docstring: "no
    # seed-threshold phase, the kickoff doc only specifies one for HRV") --
    # no "baseline_method" key exists in its result at all.
    return _metric(
        as_of_date,
        "rhr_baseline",
        value=result.get("deviation_sd"),
        unit="sd",
        window_days=baselines.DEFAULT_BASELINE_WINDOW_DAYS,
        n_days=result.get("n_days"),
        confidence=result["confidence"],
        inputs={
            "status": result["status"],
            "value_bpm": result["value"],
            "sustained_rise_flag": result.get("sustained_rise_flag"),
        },
    )


def _sleep_debt_metric(daily_rows: list[sqlite3.Row], as_of_date: str) -> DerivedMetric:
    result = baselines.compute_sleep_debt(_rows_to_tuples(daily_rows, "sleep_total_min"))
    return _metric(
        as_of_date,
        "sleep_debt",
        value=result["debt_hours"],
        unit="hours",
        window_days=result["window_days"],
        n_days=result["n_days"],
        confidence=result["confidence"],
    )


def _load_based_metrics(
    load_series: list[tuple[str, float]], as_of_date: str
) -> list[DerivedMetric]:
    """CTL/ATL/TSB/monotony/strain — all derived from the same bounded
    `load_series`, all sharing the same staleness read (see module
    docstring). Returns insufficient_data rows for all five if there's no
    load data at all as of this date, rather than raising.
    """
    if not load_series:
        return [
            _metric(as_of_date, name, value=None, confidence="insufficient_data")
            for name in ("ctl", "atl", "tsb", "monotony", "strain")
        ]

    is_stale, days_stale = _staleness(load_series[-1][0], as_of_date)
    stale_inputs = (
        {"last_real_data_date": load_series[-1][0], "days_stale": days_stale} if is_stale else None
    )

    _, ctl, atl, tsb = load_metrics.compute_ctl_atl(load_series)[-1]
    ctl_confidence = "stale" if is_stale else "full"

    ms = load_metrics.compute_monotony_strain(load_series)
    ms_confidence = "stale" if (is_stale and ms["confidence"] == "full") else ms["confidence"]
    strain_inputs = dict(stale_inputs or {})
    if ms["weekly_load"] is not None:
        strain_inputs["weekly_load"] = ms["weekly_load"]

    return [
        _metric(
            as_of_date,
            "ctl",
            value=ctl,
            unit="load",
            confidence=ctl_confidence,
            inputs=stale_inputs,
        ),
        _metric(
            as_of_date,
            "atl",
            value=atl,
            unit="load",
            confidence=ctl_confidence,
            inputs=stale_inputs,
        ),
        _metric(
            as_of_date,
            "tsb",
            value=tsb,
            unit="load",
            confidence=ctl_confidence,
            inputs=stale_inputs,
        ),
        _metric(
            as_of_date,
            "monotony",
            value=ms["monotony"],
            window_days=7,
            n_days=ms["n_days"],
            confidence=ms_confidence,
            inputs=stale_inputs,
        ),
        _metric(
            as_of_date,
            "strain",
            value=ms["strain"],
            window_days=7,
            n_days=ms["n_days"],
            confidence=ms_confidence,
            inputs=strain_inputs or None,
        ),
    ]


def _tsb_series(load_series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    ctl_atl_tsb = load_metrics.compute_ctl_atl(load_series) if load_series else []
    return [(d, tsb) for d, _ctl, _atl, tsb in ctl_atl_tsb]


def _tsb_zscore_metric(load_series: list[tuple[str, float]], as_of_date: str) -> DerivedMetric:
    tsb_series = _tsb_series(load_series)
    result = load_metrics.compute_tsb_zscore(tsb_series)
    is_stale, days_stale = _staleness(tsb_series[-1][0] if tsb_series else None, as_of_date)
    confidence = "stale" if (is_stale and result["confidence"] == "full") else result["confidence"]
    return _metric(
        as_of_date,
        "tsb_zscore",
        value=result["z_score"],
        unit="sd",
        window_days=load_metrics.DEFAULT_TSB_ZSCORE_WINDOW_DAYS,
        n_days=result["n_days"],
        confidence=confidence,
        inputs={"days_stale": days_stale} if is_stale else None,
    )


def _weight_metrics(daily_rows: list[sqlite3.Row], as_of_date: str) -> list[DerivedMetric]:
    weight_obs = _rows_to_tuples(daily_rows, "weight_kg")
    if not weight_obs:
        return [
            _metric(as_of_date, "weight_ewma", value=None, confidence="insufficient_data"),
            _metric(as_of_date, "weight_trend_slope", value=None, confidence="insufficient_data"),
        ]

    ewma_series = body_comp.compute_weight_ewma(weight_obs)
    ewma_date, ewma_value = ewma_series[-1]
    is_stale, days_stale = _staleness(ewma_date, as_of_date)
    ewma_confidence = "stale" if is_stale else "full"

    trend = body_comp.weight_trend_ols(weight_obs)
    trend_confidence = (
        "stale" if (is_stale and trend["confidence"] == "full") else trend["confidence"]
    )

    return [
        _metric(
            as_of_date,
            "weight_ewma",
            value=ewma_value,
            unit="kg",
            confidence=ewma_confidence,
            inputs={"days_stale": days_stale} if is_stale else None,
        ),
        _metric(
            as_of_date,
            "weight_trend_slope",
            value=trend["slope_kg_per_week"],
            unit="kg/week",
            window_days=trend["window_days"],
            n_days=trend["n"],
            confidence=trend_confidence,
            inputs={
                "ci_low_kg_per_week": trend["ci_low_kg_per_week"],
                "ci_high_kg_per_week": trend["ci_high_kg_per_week"],
            },
        ),
    ]


def _comp_countdown_metric(
    daily_rows: list[sqlite3.Row], config: dict[str, Any], as_of_date: str
) -> DerivedMetric:
    weight_obs = _rows_to_tuples(daily_rows, "weight_kg")
    if not weight_obs:
        return _metric(
            as_of_date,
            "comp_countdown_required_kg_per_week",
            value=None,
            confidence="insufficient_data",
        )

    ewma_series = body_comp.compute_weight_ewma(weight_obs)
    trend = body_comp.weight_trend_ols(weight_obs)
    countdown = body_comp.comp_countdown(
        current_weight_kg=ewma_series[-1][1],
        trend_slope_kg_per_week=trend["slope_kg_per_week"],
        comp_date=config["goals"]["primary"]["date"],
        weight_limit_kg=config["goals"]["primary"]["weight_division_kg"],
        today=as_of_date,
    )
    return _metric(
        as_of_date,
        "comp_countdown_required_kg_per_week",
        value=countdown["required_kg_per_week"],
        unit="kg/week",
        confidence="full" if trend["confidence"] == "full" else "partial",
        inputs={
            "kg_remaining": countdown["kg_remaining"],
            "weeks_remaining": countdown["weeks_remaining"],
            "actual_kg_per_week": countdown["actual_kg_per_week"],
            "red_flag": countdown["red_flag"],
        },
    )


def _readiness_weights(config: dict[str, Any]) -> dict[str, float]:
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
    return weights


def _readiness_score_metric(
    daily_rows: list[sqlite3.Row],
    load_series: list[tuple[str, float]],
    config: dict[str, Any],
    as_of_date: str,
    hooper_index: float | None,
) -> DerivedMetric:
    hrv_result = baselines.compute_hrv_baseline(_rows_to_tuples(daily_rows, "hrv_overnight_ms"))
    rhr_result = baselines.compute_rhr_baseline(_rows_to_tuples(daily_rows, "resting_hr"))
    sleep_obs = _rows_to_tuples(daily_rows, "sleep_total_min")
    sleep_debt_result = baselines.compute_sleep_debt(sleep_obs)
    tsb_zscore_result = load_metrics.compute_tsb_zscore(_tsb_series(load_series))
    weights = _readiness_weights(config)

    def _if_full(result: dict[str, Any], key: str) -> float | None:
        return result[key] if result.get("confidence") == "full" else None

    score_result = readiness_metrics.compute_readiness_score(
        hrv_deviation_sd=_if_full(hrv_result, "deviation_sd"),
        rhr_deviation_sd=_if_full(rhr_result, "deviation_sd"),
        last_night_sleep_hours=(sleep_obs[-1][1] / 60.0) if sleep_obs else None,
        sleep_debt_hours=sleep_debt_result["debt_hours"]
        if sleep_debt_result["confidence"] != "insufficient_data"
        else None,
        tsb_z_score=_if_full(tsb_zscore_result, "z_score"),
        hooper_index=hooper_index,
        weights=weights,
    )
    return _metric(
        as_of_date,
        "readiness_score",
        value=score_result["score"],
        confidence=score_result["confidence"],
        inputs={
            "components": score_result["components"],
            "coverage": score_result["coverage"],
            "weights": weights,
        },
    )


def compute_derived_metrics(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> list[DerivedMetric]:
    """The full Phase 4 derived-metric suite for one date. Every series
    fetched is bounded to `<= as_of_date` (see module docstring). Always
    returns one `DerivedMetric` per known metric name — a metric with no
    computable data still gets an `insufficient_data` row, never a gap.
    """
    daily_rows = _fetch_daily_metrics(conn, as_of_date)
    bjj_cal = config["training_load"]["bjj_rpe_calibration_factor"]
    load_series = _fetch_load_series(conn, bjj_cal, as_of_date)

    hooper_row = conn.execute(
        "SELECT hooper_index FROM subjective_log WHERE date = ? AND hooper_index IS NOT NULL",
        (as_of_date,),
    ).fetchone()
    hooper_index = hooper_row["hooper_index"] if hooper_row is not None else None

    return [
        _hrv_baseline_metric(daily_rows, as_of_date),
        _rhr_baseline_metric(daily_rows, as_of_date),
        _sleep_debt_metric(daily_rows, as_of_date),
        *_load_based_metrics(load_series, as_of_date),
        _tsb_zscore_metric(load_series, as_of_date),
        *_weight_metrics(daily_rows, as_of_date),
        _comp_countdown_metric(daily_rows, config, as_of_date),
        _readiness_score_metric(daily_rows, load_series, config, as_of_date, hooper_index),
    ]


def store_derived_metrics(conn: sqlite3.Connection, metrics: list[DerivedMetric]) -> int:
    """Upserts each metric on its natural key `(date, metric_name)`.
    `include_none=True` deliberately -- unlike most tables in this project,
    a `derived_daily` row that goes from a real value back to
    `insufficient_data` (e.g. a HRV baseline briefly recomputed differently)
    must actually clear the old value, not leave a stale number sitting
    under a now-wrong confidence label. Returns the number of rows written.
    """
    for metric in metrics:
        # touch_column="computed_at": derived_daily's bookkeeping column is
        # computed_at, not updated_at like most other tables here -- and it
        # must actually bump on every recompute, not just get its DEFAULT on
        # first insert and then sit stale forever (a real, previously-flagged
        # gap: a metric recomputed with a different value needs computed_at
        # to reflect that it WAS recomputed, per design principle 9).
        db.upsert(
            conn,
            "derived_daily",
            metric.to_row(include_none=True),
            ["date", "metric_name"],
            touch_column="computed_at",
        )
    return len(metrics)
