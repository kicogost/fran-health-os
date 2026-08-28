"""Weight trend and comp-countdown metrics (kickoff doc section 6).

Pure functions, deterministic, hand-verifiable — design principle 9 (every
derived number traceable) and section 12 (no LLM calls in the metrics layer,
ever). This is a deliberately partial slice of Phase 4, built early: weight has
no Garmin dependency to reconcile (Apple Health/Renpho is the sole source for
`daily_metrics.weight_kg`), so there's nothing to wait on Phase 3/Garmin for here.
HRV/RHR baselines and the readiness score are no longer blocked on Garmin data
(the 2026-08-28 backfill landed real HRV/RHR/sleep — see CLAUDE.md) but aren't
built yet either — next up. Monotony/strain and CTL/ATL/TSB are built
separately in `metrics/load.py` (ADR 0003 dropped ACWR from that module in
favor of CTL/ATL/TSB).

Nothing here writes to `derived_daily` yet. That lands with the full metric
suite in Phase 4 proper, not this early slice — these are just the functions,
called directly for now (see `scripts/weight_report.py`).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from scipy import stats

DEFAULT_EWMA_SPAN_DAYS = 7
DEFAULT_TREND_WINDOW_DAYS = 21
MIN_POINTS_FOR_TREND = 5
COMP_COUNTDOWN_RED_LINE_KG_PER_WEEK = 0.7


def compute_weight_ewma(
    observations: list[tuple[str, float]], span_days: int = DEFAULT_EWMA_SPAN_DAYS
) -> list[tuple[str, float]]:
    """Exponentially weighted moving average of weight (default 7-day span).

    `observations` must be (date, weight_kg) pairs sorted ascending by date —
    never invented or filled for missing days (design principle 6): a gap in
    logging just means fewer points feed the average, not a faked entry.

    Uses the recursive form (alpha = 2/(span+1); ewma_t = alpha*x_t +
    (1-alpha)*ewma_{t-1}), chosen because it's easy to hand-verify and doesn't
    need pandas. Note this decays per OBSERVATION, not per calendar day — a
    5-day gap between two real weigh-ins is treated the same as two back-to-back
    days. Acceptable for a scale used near-daily; revisit with calendar-
    time-weighted decay if logging becomes sparse.
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


def _insufficient_trend(window_days: int, n: int) -> dict[str, Any]:
    return {
        "slope_kg_per_week": None,
        "ci_low_kg_per_week": None,
        "ci_high_kg_per_week": None,
        "n": n,
        "window_days": window_days,
        "confidence": "insufficient_data",
    }


def weight_trend_ols(
    observations: list[tuple[str, float]],
    window_days: int = DEFAULT_TREND_WINDOW_DAYS,
    min_points: int = MIN_POINTS_FOR_TREND,
) -> dict[str, Any]:
    """OLS slope of weight vs. time over the trailing `window_days` calendar days
    ("the slope of an ordinary least squares fit over the trailing 21 days
    expressed in kg per week", kickoff doc section 6), with its 95% CI.

    `slope_kg_per_week` is a plain signed derivative: negative means losing
    weight, positive means gaining. Below `min_points` real observations in the
    window (never below 3 regardless of `min_points`, since a regression needs
    at least that many for a defined confidence interval), returns
    confidence="insufficient_data" — never report a CI from too few points as if
    it meant something.

    `observations` must be (date, weight_kg) pairs sorted ascending by date.
    """
    if not observations:
        return _insufficient_trend(window_days, 0)

    last_date = date.fromisoformat(observations[-1][0])
    cutoff = (last_date - timedelta(days=window_days - 1)).isoformat()
    windowed = [(d, w) for d, w in observations if d >= cutoff]
    n = len(windowed)
    if n < max(min_points, 3):
        return _insufficient_trend(window_days, n)

    first_date = date.fromisoformat(windowed[0][0])
    x = [(date.fromisoformat(d) - first_date).days for d, _ in windowed]
    y = [w for _, w in windowed]

    fit = stats.linregress(x, y)
    slope_kg_per_week = fit.slope * 7
    stderr_kg_per_week = fit.stderr * 7
    t_crit = stats.t.ppf(0.975, df=n - 2)
    half_width = t_crit * stderr_kg_per_week

    return {
        "slope_kg_per_week": slope_kg_per_week,
        "ci_low_kg_per_week": slope_kg_per_week - half_width,
        "ci_high_kg_per_week": slope_kg_per_week + half_width,
        "n": n,
        "window_days": window_days,
        "confidence": "full",
    }


def comp_countdown(
    *,
    current_weight_kg: float,
    trend_slope_kg_per_week: float | None,
    comp_date: str,
    weight_limit_kg: float,
    today: str,
    red_line_kg_per_week: float = COMP_COUNTDOWN_RED_LINE_KG_PER_WEEK,
) -> dict[str, Any]:
    """Comp-weight countdown (kickoff doc section 6): kg remaining, weeks
    remaining, required kg/week, current actual kg/week, and the red-line flag
    ("if required exceeds 0.7 kg/week, mark it red — past that point the cut
    stops being a fat loss problem and starts being a performance problem").

    Sign convention, chosen so the two rates are directly comparable at a
    glance: both `required_kg_per_week` and `actual_kg_per_week` are POSITIVE
    when weight needs to (required) / is (actual) trending DOWN.
    `trend_slope_kg_per_week` (from `weight_trend_ols`) is a raw signed
    derivative — negative when actually losing weight — so `actual_kg_per_week`
    here is its negation.
    """
    comp_d = date.fromisoformat(comp_date)
    today_d = date.fromisoformat(today)
    days_remaining = (comp_d - today_d).days
    weeks_remaining = days_remaining / 7.0
    kg_remaining = current_weight_kg - weight_limit_kg

    required_kg_per_week = kg_remaining / weeks_remaining if weeks_remaining > 0 else None
    actual_kg_per_week = -trend_slope_kg_per_week if trend_slope_kg_per_week is not None else None

    red_flag = required_kg_per_week is not None and required_kg_per_week > red_line_kg_per_week

    return {
        "current_weight_kg": current_weight_kg,
        "weight_limit_kg": weight_limit_kg,
        "kg_remaining": kg_remaining,
        "days_remaining": days_remaining,
        "weeks_remaining": weeks_remaining,
        "required_kg_per_week": required_kg_per_week,
        "actual_kg_per_week": actual_kg_per_week,
        "red_flag": red_flag,
    }
