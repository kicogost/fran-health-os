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
DEFAULT_NIGHTLY_NEED_HOURS = 8.0

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
    deviation_sd = 0.0 if sd == 0 else (latest_value - median) / sd
    status = "high" if deviation_sd > 1 else "low" if deviation_sd < -1 else "balanced"

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
    shared one.
    """
    n = len(observations)
    if n < min_days:
        return {
            "value": observations[-1][1] if observations else None,
            "status": "insufficient_data",
            "n_days": n,
            "confidence": "insufficient_data",
            "sustained_rise_flag": False,
        }

    values = [v for _, v in observations]
    latest_idx = n - 1
    window = values[max(0, latest_idx - window_days + 1) : latest_idx + 1]
    median, sd = _window_median_sd(window)
    deviation_sd = _rolling_deviation_sd(values, latest_idx, window_days, min_days)
    status = "high" if deviation_sd > 1 else "low" if deviation_sd < -1 else "balanced"

    last_3 = [
        _rolling_deviation_sd(values, i, window_days, min_days) for i in range(max(0, n - 3), n)
    ]
    sustained_rise_flag = len(last_3) == 3 and all(d is not None and d > 1 for d in last_3)

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
