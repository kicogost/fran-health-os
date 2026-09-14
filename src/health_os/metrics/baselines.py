"""HRV baseline, RHR baseline, and sleep debt (kickoff doc section 6).

Pure functions, deterministic, hand-verifiable — same rules as
metrics/body_comp.py and metrics/load.py (design principle 9, section 12: no
LLM calls in this layer, ever). Unblocked by the 2026-08-28 Garmin backfill —
see CLAUDE.md's Phase 2 summary for what that data actually looks like.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any

DEFAULT_BASELINE_WINDOW_DAYS = 60
DEFAULT_BASELINE_MIN_DAYS = 21
DEFAULT_SLEEP_DEBT_WINDOW_DAYS = 14

# ADR 0007 (2026-08-30): lowered from a flat 8.0h point target to 7.0h — the
# LOW edge of the National Sleep Foundation's own adult recommendation, a
# 7-9h range, not a point value. Debt only accrues below this floor now,
# consistent with `metrics/readiness.py: SLEEP_BAND_LOW_HOURS` treating
# anything in the adequate range as fully credited, not just exactly-8h.
# The 14-day window itself is unchanged — genuinely unresolved either way
# (no study anywhere compares 7 vs 14 vs 21 vs 30 days for real-world debt
# tracking; the original 14-day pick was shared industry convention, not
# shared evidence, and staying at 14 is exactly as evidence-free as moving
# it, so there's nothing to change toward).
DEFAULT_NIGHTLY_NEED_HOURS = 7.0

# The HIGH edge of the same NSF 7-9h band — added 2026-09-09 for the Trends
# page's per-chart window-average feature (`api/trends.py`), which needed to
# classify a window's average sleep duration as short/in-band/long, not just
# "in deficit or not" (the only thing the debt calc above needs the low edge
# for). No new judgment call: this is the same band ADR 0007 already
# documented in prose, just given an explicit constant now that a second
# caller needs the upper number too.
DEFAULT_NIGHTLY_NEED_UPPER_HOURS = 9.0

# Francisco's own seed thresholds (kickoff doc section 6), used only while the
# 60-day computed-baseline window is filling (21-59 total observations). The
# gaps the kickoff doc didn't specify (85-90ms, below 75ms) are interpretation
# choices, not given numbers — documented here so they're easy to correct:
# 85-90ms folds into "balanced" (closer to the green end than the capped
# range), below 75ms folds into "low" (worse than "capped").
SEED_GREEN_MS = 90.0
SEED_CAPPED_RANGE_MS = (75.0, 85.0)


def _window_median_sd(values: list[float]) -> tuple[float, float]:
    return statistics.median(values), statistics.pstdev(values)


def _status_from_deviation_sd(deviation_sd: float) -> str:
    """The +-1 SD -> high/low/balanced mapping shared by every baseline
    classification in this module, factored into one place so
    `compute_hrv_baseline()`, `compute_rhr_baseline()`, and any external
    caller via `classify_deviation()` below all apply the identical rule —
    this project's own repeated lesson about two independent copies of "the
    same thing" silently drifting apart (see CLAUDE.md's several sections on
    this, e.g. the sleep-quality-blend and TSB-staleness fixes).
    """
    if deviation_sd > 1:
        return "high"
    if deviation_sd < -1:
        return "low"
    return "balanced"


def classify_deviation(value: float, median: float, sd: float) -> tuple[float, str]:
    """Deviation of `value` from (`median`, `sd`) in SD units, plus the same
    high/low/balanced status label `compute_hrv_baseline()`/
    `compute_rhr_baseline()` apply to their own latest observation.

    Public specifically so a caller holding an already-computed baseline
    (e.g. `api/trends.py`, classifying a windowed AVERAGE rather than the
    single latest observation those two functions classify internally) can
    reuse the exact same +-1 SD rule instead of re-deriving a second copy of
    it that could quietly drift out of sync with this module's own.
    """
    deviation_sd = 0.0 if sd == 0 else (value - median) / sd
    return deviation_sd, _status_from_deviation_sd(deviation_sd)


def compute_hrv_baseline(
    observations: list[tuple[str, float]],
    *,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    min_days: int = DEFAULT_BASELINE_MIN_DAYS,
) -> dict[str, Any]:
    """HRV baseline status as of the most recent observation.

    Two-phase per kickoff doc section 6: below `min_days` (21) total
    observations, `insufficient_data`. From `min_days` up to `window_days`
    (60), uses the seed thresholds above as a placeholder while the rolling
    window fills. From `window_days` onward, switches to the properly
    computed baseline — `window_days`-day rolling MEDIAN and population SD,
    status "balanced" within +-1 SD, "low"/"high" beyond.

    The switchover isn't a separate log statement — it's visible in
    `baseline_method` on every call. Once `n` crosses `window_days`, callers
    see `"computed"` instead of `"seed"` from then on; that transition,
    recorded on whichever `derived_daily` rows span it, *is* the audit trail
    (design principle 9).

    `observations` must be (date, hrv_ms) pairs, sorted ascending, with no
    None values (filter those out before calling — a missing night is
    "there's no observation for this date," not a zero).
    """
    n = len(observations)
    if n < min_days:
        return {
            "value": observations[-1][1] if observations else None,
            "status": "insufficient_data",
            "baseline_method": "insufficient_data",
            "n_days": n,
            "confidence": "insufficient_data",
        }

    latest_value = observations[-1][1]

    if n < window_days:
        low, high = SEED_CAPPED_RANGE_MS
        if latest_value > SEED_GREEN_MS:
            status = "balanced"
        elif low <= latest_value <= high:
            status = "capped"
        elif latest_value < low:
            status = "low"
        else:  # between high and SEED_GREEN_MS -- undocumented gap, see module docstring
            status = "balanced"
        return {
            "value": latest_value,
            "status": status,
            "baseline_method": "seed",
            "n_days": n,
            "confidence": "provisional",
        }

    window = [v for _, v in observations[-window_days:]]
    median, sd = _window_median_sd(window)
    deviation_sd, status = classify_deviation(latest_value, median, sd)

    return {
        "value": latest_value,
        "baseline_median": median,
        "baseline_sd": sd,
        "deviation_sd": deviation_sd,
        "status": status,
        "baseline_method": "computed",
        "n_days": len(window),
        "confidence": "full",
    }


def _rolling_deviation_sd(
    values: list[float], end_idx: int, window_days: int, min_days: int
) -> float | None:
    """Deviation in SD units of `values[end_idx]` from the median/SD of the
    trailing `window_days` ending at `end_idx` (inclusive). `None` if fewer
    than `min_days` observations exist up to that point.
    """
    if end_idx + 1 < min_days:
        return None
    window = values[max(0, end_idx - window_days + 1) : end_idx + 1]
    median, sd = _window_median_sd(window)
    return 0.0 if sd == 0 else (values[end_idx] - median) / sd


def compute_rhr_baseline(
    observations: list[tuple[str, float]],
    *,
    window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    min_days: int = DEFAULT_BASELINE_MIN_DAYS,
) -> dict[str, Any]:
    """RHR baseline — same structure as HRV (60-day rolling median/SD, needs
    >=21 days), but no seed-threshold phase (the kickoff doc only specifies
    one for HRV): status is `insufficient_data` until there's a real baseline
    to compute.

    `sustained_rise_flag`: True when the last 3 consecutive days each show
    >1 SD elevation above their own trailing baseline — a sustained rise, not
    one noisy high reading, per kickoff doc section 6. Each of the 3 days uses
    its own trailing window (the window slides day to day), not a single
    shared one. `None` (never a silent `False`, design principle 6) whenever
    any of those 3 required sub-baselines can't be computed yet — the
    earliest of the 3 lookbacks needs `n >= min_days + 2` total observations,
    two more than `min_days` itself, since it needs its own trailing window
    of `min_days` PLUS 2 more days for the later two of the 3 to slide over.
    Below that, "not sustained-elevated" and "can't tell yet" would otherwise
    be silently indistinguishable.
    """
    n = len(observations)
    if n < min_days:
        return {
            "value": observations[-1][1] if observations else None,
            "status": "insufficient_data",
            "n_days": n,
            "confidence": "insufficient_data",
            "sustained_rise_flag": None,
        }

    values = [v for _, v in observations]
    latest_idx = n - 1
    window = values[max(0, latest_idx - window_days + 1) : latest_idx + 1]
    median, sd = _window_median_sd(window)
    deviation_sd = _rolling_deviation_sd(values, latest_idx, window_days, min_days)
    status = _status_from_deviation_sd(deviation_sd)

    last_3 = [
        _rolling_deviation_sd(values, i, window_days, min_days) for i in range(max(0, n - 3), n)
    ]
    sustained_rise_flag: bool | None
    if len(last_3) < 3 or any(d is None for d in last_3):
        # Not yet computable (n < min_days + 2) -- "unknown", never a silent
        # False that would look identical to a genuinely-checked "not
        # elevated" result.
        sustained_rise_flag = None
    else:
        sustained_rise_flag = all(d > 1 for d in last_3)

    return {
        "value": values[-1],
        "baseline_median": median,
        "baseline_sd": sd,
        "deviation_sd": deviation_sd,
        "status": status,
        "n_days": len(window),
        "confidence": "full",
        "sustained_rise_flag": sustained_rise_flag,
    }


def compute_sleep_debt(
    observations: list[tuple[str, float]],
    *,
    window_days: int = DEFAULT_SLEEP_DEBT_WINDOW_DAYS,
    nightly_need_hours: float = DEFAULT_NIGHTLY_NEED_HOURS,
) -> dict[str, Any]:
    """Rolling 14-day sleep debt in hours: sum of (need - actual) per night
    over the trailing calendar window. Positive = net deficit, negative = net
    surplus. `observations` are (date, sleep_total_min) pairs, sorted
    ascending, with no None values — a missing night is excluded from the sum
    entirely, never filled with 0 or the full need (design principle 6).

    Windowed by calendar date (like `body_comp.weight_trend_ols`), not just
    "last N observations" — a gap in logging shouldn't silently stretch the
    window to cover more than 14 real days.
    """
    if not observations:
        return {
            "debt_hours": None,
            "n_days": 0,
            "window_days": window_days,
            "confidence": "insufficient_data",
        }

    last_date = date.fromisoformat(observations[-1][0])
    cutoff = (last_date - timedelta(days=window_days - 1)).isoformat()
    windowed = [(d, minutes) for d, minutes in observations if d >= cutoff]

    debt_hours = sum(nightly_need_hours - (minutes / 60.0) for _, minutes in windowed)
    n = len(windowed)
    confidence = "full" if n >= window_days else "partial" if n > 0 else "insufficient_data"

    return {
        "debt_hours": debt_hours,
        "n_days": n,
        "window_days": window_days,
        "confidence": confidence,
    }
