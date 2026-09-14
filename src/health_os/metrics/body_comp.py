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

**Body fat % / fat mass added 2026-09-11** (Francisco, once the Renpho CSV
body-composition backfill landed real `body_fat_pct` data: "is my weight
loss/gain coming from fat or muscle"). Reuses this module's existing
weight-tracking machinery rather than inventing a second smoothing/trend
approach: `compute_weight_ewma()` is already fully generic (no unit baked
into its own logic or return shape) and is called UNCHANGED for both the
fat-mass and body-fat-% series below; `weight_trend_ols()` is likewise
reused unchanged for fat mass (fat mass is genuinely measured in kg, so its
kg-labeled field names are accurate, not just borrowed) — only body fat %
needed a real sibling, `body_fat_pct_trend_ols()`, because its own unit
(percentage points) would make `weight_trend_ols()`'s kg-labeled field names
wrong. See `compute_fat_mass_series()` and `body_fat_pct_trend_ols()` below.
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


def _insufficient_trend_generic(window_days: int, n: int) -> dict[str, Any]:
    return {
        "slope_per_week": None,
        "ci_low_per_week": None,
        "ci_high_per_week": None,
        "n": n,
        "window_days": window_days,
        "confidence": "insufficient_data",
    }


def _trend_ols_generic(
    observations: list[tuple[str, float]],
    window_days: int,
    min_points: int,
) -> dict[str, Any]:
    """Shared OLS-over-trailing-window math behind both `weight_trend_ols()`
    and `body_fat_pct_trend_ols()` (added 2026-09-11, see that function's own
    docstring for why body fat % needed a sibling rather than a direct call
    to `weight_trend_ols()`) — one implementation of the regression itself,
    generically-keyed (`slope_per_week` etc., no unit baked into the name),
    so the two public wrappers can each rename the keys to whatever unit
    their own series is actually in without duplicating the math.

    `observations` must be (date, value) pairs sorted ascending by date.
    Below `min_points` real observations in the window (never below 3
    regardless of `min_points`, since a regression needs at least that many
    for a defined confidence interval), returns confidence="insufficient_data"
    — never report a CI from too few points as if it meant something.
    """
    if not observations:
        return _insufficient_trend_generic(window_days, 0)

    last_date = date.fromisoformat(observations[-1][0])
    cutoff = (last_date - timedelta(days=window_days - 1)).isoformat()
    windowed = [(d, w) for d, w in observations if d >= cutoff]
    n = len(windowed)
    if n < max(min_points, 3):
        return _insufficient_trend_generic(window_days, n)

    first_date = date.fromisoformat(windowed[0][0])
    x = [(date.fromisoformat(d) - first_date).days for d, _ in windowed]
    y = [w for _, w in windowed]

    fit = stats.linregress(x, y)
    slope_per_week = fit.slope * 7
    stderr_per_week = fit.stderr * 7
    t_crit = stats.t.ppf(0.975, df=n - 2)
    half_width = t_crit * stderr_per_week

    return {
        "slope_per_week": slope_per_week,
        "ci_low_per_week": slope_per_week - half_width,
        "ci_high_per_week": slope_per_week + half_width,
        "n": n,
        "window_days": window_days,
        "confidence": "full",
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
    Also the correct function to reuse directly for a FAT MASS (kg) series
    (`compute_fat_mass_series()` below) — fat mass is genuinely measured in
    kg, same as weight, so this function's kg-labeled field names are still
    accurate, not just borrowed. Delegates to `_trend_ols_generic()` — see
    `body_fat_pct_trend_ols()` for the one series (body fat %) whose own
    units are NOT kg, which is why that one is a separate, thin sibling
    rather than a second call to this function.
    """
    generic = _trend_ols_generic(observations, window_days, min_points)
    return {
        "slope_kg_per_week": generic["slope_per_week"],
        "ci_low_kg_per_week": generic["ci_low_per_week"],
        "ci_high_kg_per_week": generic["ci_high_per_week"],
        "n": generic["n"],
        "window_days": generic["window_days"],
        "confidence": generic["confidence"],
    }


def body_fat_pct_trend_ols(
    observations: list[tuple[str, float]],
    window_days: int = DEFAULT_TREND_WINDOW_DAYS,
    min_points: int = MIN_POINTS_FOR_TREND,
) -> dict[str, Any]:
    """Same OLS-over-trailing-window math as `weight_trend_ols()` — identical
    `_trend_ols_generic()` helper underneath, not a copy-pasted second
    implementation — applied to a body-fat-% series instead of weight.

    `weight_trend_ols()` isn't reused directly here because ITS returned
    field names bake in a kg unit (`slope_kg_per_week`), which would be
    silently wrong/misleading for a percentage-point slope. This is a thin,
    honestly-labeled sibling (`slope_pct_per_week` etc.) rather than a
    re-derivation of the regression itself — added 2026-09-11 alongside
    `compute_fat_mass_series()` (see CLAUDE.md's Renpho body-composition
    section) so body fat %'s own trend can be tracked with the exact same
    rigor as weight's, per this project's established "never show a raw
    single-day number as the headline, always smooth + trend" discipline.

    `observations` must be (date, body_fat_pct) pairs sorted ascending by
    date.
    """
    generic = _trend_ols_generic(observations, window_days, min_points)
    return {
        "slope_pct_per_week": generic["slope_per_week"],
        "ci_low_pct_per_week": generic["ci_low_per_week"],
        "ci_high_pct_per_week": generic["ci_high_per_week"],
        "n": generic["n"],
        "window_days": generic["window_days"],
        "confidence": generic["confidence"],
    }


def compute_fat_mass_series(
    weight_obs: list[tuple[str, float]], body_fat_pct_obs: list[tuple[str, float]]
) -> list[tuple[str, float]]:
    """Fat mass (kg) = weight_kg * body_fat_pct / 100 — computed ONLY for
    dates where BOTH a real `weight_kg` and a real `body_fat_pct` reading
    exist that same day (design principle 6: never invented/interpolated for
    a date missing either input — a day with just a body-fat% reading and no
    weigh-in that day, or vice versa, contributes nothing here).

    `weight_obs`/`body_fat_pct_obs` are each (date, value) pairs — the exact
    shape `compute_weight_ewma()`/`weight_trend_ols()` already take, so the
    result of this join can be fed straight back into either of those two
    functions completely unchanged (which is exactly how the fat-mass EWMA
    and fat-mass OLS trend below are built — no new smoothing/trend math for
    this new metric, per CLAUDE.md's own ask). Order follows `weight_obs`;
    callers already fetch these ascending by date (`api/trends.py:
    _fetch_col_obs()`), so the result is ascending too.
    """
    pct_by_date = dict(body_fat_pct_obs)
    result: list[tuple[str, float]] = []
    for d, weight_kg in weight_obs:
        pct = pct_by_date.get(d)
        if pct is None:
            continue
        result.append((d, weight_kg * pct / 100.0))
    return result


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
