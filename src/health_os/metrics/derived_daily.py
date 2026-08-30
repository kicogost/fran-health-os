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

**CTL/ATL/TSB honesty note, updated 2026-08-30**: this module used to feed
CTL/ATL/TSB/monotony/strain from `metrics.load.build_daily_load_series()`,
which only walked from the first to the LAST OBSERVED date in its
`activities.training_load` + `bjj_sessions.computed_load` inputs — a real
problem, since that column is almost always NULL (CLAUDE.md's training-load
build-out section) and the series could silently stop advancing for months.
That's now fixed at the source: `metrics.strain.build_activity_based_load_
series()` computes a REAL per-day value (TRIMP wherever `avg_hr` exists,
Foster's method for BJJ) for every day through `as_of_date`, including
genuine 0.0 rest days, so there's no gap left to silently pad with invented
zeros — `_load_based_metrics()`/`_tsb_zscore_metric()` no longer have a
"stale" branch at all (removed, not left dead — see their own docstrings).

The weight/EWMA metrics below still use the ORIGINAL staleness mechanism
(`load_metrics.load_staleness()`) — a gap in weigh-ins is a genuinely
different, still-real problem (nothing about the load-series fix changes
whether Francisco actually weighed himself recently), so that check remains
exactly as it was.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from health_os.core import db
from health_os.core.models import DerivedMetric
from health_os.metrics import baselines, body_comp
from health_os.metrics import load as load_metrics
from health_os.metrics import readiness as readiness_metrics
from health_os.metrics import strain as strain_metrics


def _rows_to_tuples(rows: list[sqlite3.Row], value_col: str) -> list[tuple[str, float]]:
    return [(r["date"], r[value_col]) for r in rows if r[value_col] is not None]


def _fetch_daily_metrics(conn: sqlite3.Connection, as_of_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM daily_metrics WHERE date <= ? ORDER BY date", (as_of_date,)
    ).fetchall()


def _fetch_load_series(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> list[tuple[str, float]]:
    """Rebuilt 2026-08-30 to reuse `metrics.strain.build_activity_based_load_
    series()` -- the same TRIMP/Foster per-day computation the Training page
    and the Daily Strain ring use — instead of `activities.training_load`
    (largely NULL, see CLAUDE.md's training-load build-out notes). Without
    this, the persisted `derived_daily` CTL/ATL/TSB/monotony/strain history
    would keep reflecting a sparser, different picture of training load than
    the live Training page now shows. Already bounded to `<= as_of_date`
    internally (see this module's own future-leakage discipline note above).
    """
    return strain_metrics.build_activity_based_load_series(conn, config, as_of_date)


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
    `load_series`. Returns insufficient_data rows for all five if there's no
    load data at all as of this date, rather than raising.

    No "stale" confidence branch anymore (removed 2026-08-30, alongside the
    switch to `strain.build_activity_based_load_series()`): that branch
    existed because the OLD `activities.training_load`-based series could
    silently stop updating for months while still reporting a non-empty
    series (see git history / ADR-adjacent CLAUDE.md notes on the
    training-load coverage gap). The new series always walks through to
    `as_of_date` itself, computing a REAL, confirmed value for every day in
    between (including genuine 0.0 rest days) — so `load_series[-1][0]` is
    now always `as_of_date` whenever the series is non-empty, and the old
    staleness check could structurally never fire again. Removed rather
    than left in place looking like it still does something.
    """
    if not load_series:
        return [
            _metric(as_of_date, name, value=None, confidence="insufficient_data")
            for name in ("ctl", "atl", "tsb", "monotony", "strain")
        ]

    _, ctl, atl, tsb = load_metrics.compute_ctl_atl(load_series)[-1]
    ms = load_metrics.compute_monotony_strain(load_series)

    return [
        _metric(as_of_date, "ctl", value=ctl, unit="load", confidence="full"),
        _metric(as_of_date, "atl", value=atl, unit="load", confidence="full"),
        _metric(as_of_date, "tsb", value=tsb, unit="load", confidence="full"),
        _metric(
            as_of_date,
            "monotony",
            value=ms["monotony"],
            window_days=7,
            n_days=ms["n_days"],
            confidence=ms["confidence"],
        ),
        _metric(
            as_of_date,
            "strain",
            value=ms["strain"],
            window_days=7,
            n_days=ms["n_days"],
            confidence=ms["confidence"],
            inputs={"weekly_load": ms["weekly_load"]} if ms["weekly_load"] is not None else None,
        ),
    ]


def _tsb_series(load_series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    ctl_atl_tsb = load_metrics.compute_ctl_atl(load_series) if load_series else []
    return [(d, tsb) for d, _ctl, _atl, tsb in ctl_atl_tsb]


def _tsb_zscore_metric(load_series: list[tuple[str, float]], as_of_date: str) -> DerivedMetric:
    """No "stale" branch -- see `_load_based_metrics()`'s docstring for why
    that's no longer reachable with the new activity-based load series.
    """
    tsb_series = _tsb_series(load_series)
    result = load_metrics.compute_tsb_zscore(tsb_series)
    return _metric(
        as_of_date,
        "tsb_zscore",
        value=result["z_score"],
        unit="sd",
        window_days=load_metrics.DEFAULT_TSB_ZSCORE_WINDOW_DAYS,
        n_days=result["n_days"],
        confidence=result["confidence"],
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
    is_stale, days_stale = load_metrics.load_staleness(ewma_date, as_of_date)
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
            "subjective": config["readiness_score"]["weight_subjective"],
        }
    )
    return weights


def _readiness_score_metric(
    daily_rows: list[sqlite3.Row],
    config: dict[str, Any],
    as_of_date: str,
    hooper_index: float | None,
) -> DerivedMetric:
    """ADR 0007 (2026-08-30) removed TSB from this composite entirely -- no
    longer takes `load_series`/computes a TSB z-score here at all. TSB is
    still persisted separately by `_tsb_zscore_metric()` (its own
    `derived_daily` row, still fed from `load_series` at the real call site
    below), just not folded into `readiness_score` anymore.
    """
    hrv_result = baselines.compute_hrv_baseline(_rows_to_tuples(daily_rows, "hrv_overnight_ms"))
    rhr_result = baselines.compute_rhr_baseline(_rows_to_tuples(daily_rows, "resting_hr"))
    sleep_obs = _rows_to_tuples(daily_rows, "sleep_total_min")
    sleep_quality_obs = _rows_to_tuples(daily_rows, "sleep_score")
    sleep_debt_result = baselines.compute_sleep_debt(sleep_obs)
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
        # Garmin's own sleep_score (REM/deep/restlessness/timing) -- same fix
        # and same "last element == as_of_date" convention as
        # coach/briefing.py's identical call site, kept in sync deliberately.
        sleep_quality_score=sleep_quality_obs[-1][1] if sleep_quality_obs else None,
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
    load_series = _fetch_load_series(conn, config, as_of_date)

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
        _readiness_score_metric(daily_rows, config, as_of_date, hooper_index),
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
