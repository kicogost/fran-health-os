"""Training load metrics: ACWR, monotony/strain (Foster), and CTL/ATL/TSB
(Banister impulse-response model) — kickoff doc section 6, research grounding
in CLAUDE.md (2026-08-27 "proprietary training load" discussion).

Pure functions, deterministic, hand-verifiable — same rules as metrics/body_comp.py
(design principle 9, section 12: no LLM calls in this layer, ever).

**On ACWR specifically**: the sports science literature has moved against it —
Impellizzeri et al. and multiple systematic reviews document severe mathematical
coupling and inconsistent injury association. It's implemented here because the
kickoff doc explicitly asked for it, but it should be read as a rough ramp-rate
signal, not a validated predictor. CTL/ATL/TSB (the same math TrainingPeaks calls
the Performance Manager Chart) is the better-regarded alternative, kept alongside
it rather than instead of it.

**Zero is a real value here, unlike weight.** A rest day genuinely has zero
training load — it isn't "missing data" the way a day with no weigh-in is
(design principle 6). `build_daily_load_series()` walks every calendar day and
fills non-training days with 0.0 accordingly; the metric functions below all
assume they're given that kind of complete, zero-filled, date-sorted series.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from math import exp
from typing import Any

DEFAULT_CTL_TAU_DAYS = 42.0  # "fitness", slow to build, slow to fade
DEFAULT_ATL_TAU_DAYS = 7.0  # "fatigue", fast to build, fast to fade
DEFAULT_ACWR_ACUTE_DAYS = 7
DEFAULT_ACWR_CHRONIC_DAYS = 28
ACWR_SWEET_SPOT = (0.8, 1.3)
ACWR_RAMP_FLAG = 1.5
MONOTONY_FLAG = 2.0


def build_daily_load_series(
    activity_loads: list[tuple[str, float]],
    bjj_loads: list[tuple[str, float]],
    *,
    bjj_calibration_factor: float = 1.0,
) -> list[tuple[str, float]]:
    """Combine `activities.training_load` (any source) with BJJ manual-log
    `computed_load` (scaled by `config/athlete.yaml:
    training_load.bjj_rpe_calibration_factor` — 1.0/uncalibrated until Garmin
    data exists to fit it properly, kickoff doc section 2.4) into one total per
    calendar day, then walks every day from the first observed date to the last
    — filling rest days with 0.0, not skipping them, since that's a real zero.

    Known limitation: activities with no `training_load` (most non-Strava rows
    right now — Apple Health's parser doesn't populate it, Garmin isn't loaded
    yet) contribute nothing here, so days dominated by those sessions will
    understate true load until richer sources land.
    """
    if not activity_loads and not bjj_loads:
        return []

    totals: dict[str, float] = {}
    for day, load in activity_loads:
        totals[day] = totals.get(day, 0.0) + load
    for day, load in bjj_loads:
        totals[day] = totals.get(day, 0.0) + load * bjj_calibration_factor

    all_dates = sorted(totals)
    start = date.fromisoformat(all_dates[0])
    end = date.fromisoformat(all_dates[-1])

    series = []
    current = start
    while current <= end:
        iso = current.isoformat()
        series.append((iso, totals.get(iso, 0.0)))
        current += timedelta(days=1)
    return series


def compute_acwr(
    daily_loads: list[tuple[str, float]],
    *,
    acute_window_days: int = DEFAULT_ACWR_ACUTE_DAYS,
    chronic_window_days: int = DEFAULT_ACWR_CHRONIC_DAYS,
) -> dict[str, Any]:
    """Acute:chronic workload ratio, as of the last date in `daily_loads`.
    Acute = trailing 7-day load sum. Chronic = 28-day rolling average of that
    same 7-day-sum series. Sweet spot 0.8-1.3; >1.5 flagged as ramping too
    fast, <0.8 as detraining — see module docstring for the caveat on how much
    to trust this number.
    """
    n = len(daily_loads)
    min_required = acute_window_days + chronic_window_days
    if n < min_required:
        return {
            "acwr": None,
            "acute_load": None,
            "chronic_load": None,
            "n_days": n,
            "confidence": "insufficient_data",
        }

    loads = [load for _, load in daily_loads]

    def rolling_sum(end_idx: int, window: int) -> float:
        return sum(loads[end_idx - window + 1 : end_idx + 1])

    acute = rolling_sum(n - 1, acute_window_days)
    seven_day_sums = [rolling_sum(i, acute_window_days) for i in range(n - chronic_window_days, n)]
    chronic = sum(seven_day_sums) / len(seven_day_sums)

    acwr = acute / chronic if chronic > 0 else None
    flag = None
    if acwr is not None:
        if acwr > ACWR_RAMP_FLAG:
            flag = "ramping_too_fast"
        elif acwr < ACWR_SWEET_SPOT[0]:
            flag = "detraining"
        elif acwr <= ACWR_SWEET_SPOT[1]:
            flag = "sweet_spot"
        else:
            flag = "moderate"

    return {
        "acwr": acwr,
        "acute_load": acute,
        "chronic_load": chronic,
        "n_days": n,
        "confidence": "full",
        "flag": flag,
    }


def compute_monotony_strain(
    daily_loads: list[tuple[str, float]], window_days: int = 7
) -> dict[str, Any]:
    """Training monotony and strain (Foster), over the trailing `window_days`.
    Monotony = mean daily load / population SD of daily load; strain = weekly
    load total x monotony. Flag monotony > 2.0 — no real hard/easy contrast in
    the week, the classic pattern before things go wrong.

    Population (not sample) SD, since the trailing window is the complete set
    of days being described, not a sample estimating a larger population.
    Undefined (not a fabricated large number) when every day in the window has
    identical load — SD = 0 makes the ratio mathematically undefined, not
    "very high"; a genuinely constant week is rare enough in real data that
    this isn't worth inventing a sentinel value for.
    """
    n = len(daily_loads)
    if n < window_days:
        return {
            "monotony": None,
            "strain": None,
            "weekly_load": None,
            "n_days": n,
            "confidence": "insufficient_data",
        }

    recent = [load for _, load in daily_loads[-window_days:]]
    mean_load = statistics.mean(recent)
    sd_load = statistics.pstdev(recent)
    weekly_load = sum(recent)

    if sd_load == 0:
        return {
            "monotony": None,
            "strain": None,
            "weekly_load": weekly_load,
            "n_days": window_days,
            "confidence": "undefined_zero_variance",
        }

    monotony = mean_load / sd_load
    strain = weekly_load * monotony

    return {
        "monotony": monotony,
        "strain": strain,
        "weekly_load": weekly_load,
        "n_days": window_days,
        "confidence": "full",
        "flag_high_monotony": monotony > MONOTONY_FLAG,
    }


def compute_ctl_atl(
    daily_loads: list[tuple[str, float]],
    *,
    ctl_tau_days: float = DEFAULT_CTL_TAU_DAYS,
    atl_tau_days: float = DEFAULT_ATL_TAU_DAYS,
) -> list[tuple[str, float, float, float]]:
    """CTL ("fitness"), ATL ("fatigue"), and TSB = CTL - ATL ("freshness") —
    the Banister impulse-response model. Standard exponential-decay recursive
    form:

        value_today = value_yesterday + (load_today - value_yesterday) * (1 - exp(-1/tau))

    Both series are seeded at the first day's raw load (there's no "day zero"
    fitness/fatigue to inherit from). With years of Strava history behind most
    dates of interest, the seed's influence is negligible by "today" regardless
    — exponential decay forgets the seed after a few multiples of tau — so this
    only meaningfully affects the very start of the series, not current values.

    Returns the full (date, ctl, atl, tsb) series, not just the latest point —
    useful for charting fitness/fatigue trends once the dashboard lands.
    """
    if not daily_loads:
        return []

    ctl_alpha = 1 - exp(-1 / ctl_tau_days)
    atl_alpha = 1 - exp(-1 / atl_tau_days)

    series: list[tuple[str, float, float, float]] = []
    ctl: float | None = None
    atl: float | None = None
    for day, load in daily_loads:
        ctl = load if ctl is None else ctl + (load - ctl) * ctl_alpha
        atl = load if atl is None else atl + (load - atl) * atl_alpha
        series.append((day, ctl, atl, ctl - atl))
    return series
