"""Training load metrics: monotony/strain (Foster) and CTL/ATL/TSB (Banister
impulse-response model) — kickoff doc section 6, research grounding in CLAUDE.md
(2026-08-27 "proprietary training load" discussion), ADR 0003.

Pure functions, deterministic, hand-verifiable — same rules as metrics/body_comp.py
(design principle 9, section 12: no LLM calls in this layer, ever).

**No ACWR here — see ADR 0003.** The kickoff doc originally asked for it, but the
sports science literature has moved against it (Impellizzeri et al. and multiple
systematic reviews document severe mathematical coupling and inconsistent injury
association), and Francisco asked to drop it once that was surfaced rather than
keep a metric flagged as scientifically shaky. CTL/ATL/TSB (the same math
TrainingPeaks calls the Performance Manager Chart) is the leading-data
replacement — kept as the sole training-load-ratio signal here.

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
MONOTONY_FLAG = 2.0


def build_daily_load_series(
    activity_loads: list[tuple[str, float]],
    bjj_loads: list[tuple[str, float]],
    *,
    bjj_calibration_factor: float = 1.0,
) -> list[tuple[str, float]]:
    """Combine `activities.training_load` (any source) with BJJ manual-log
    `computed_load` (scaled by `config/athlete.yaml:
    training_load.bjj_rpe_calibration_factor` — still 1.0/uncalibrated, kickoff
    doc section 2.4) into one total per calendar day, then walks every day from
    the first observed date to the last — filling rest days with 0.0, not
    skipping them, since that's a real zero.

    Known limitation, confirmed still open even after Garmin's backfill
    (2026-08-28): Garmin's bulk export has no `training_load` scalar at all
    (checked — see `ingest/garmin_bulk.py`'s module docstring), so the kickoff
    doc's original calibration plan ("calibrate against Garmin's training load
    values") has nothing to calibrate against yet. `aerobic_te`/`anaerobic_te`
    (which Garmin does provide) may be the better calibration target instead —
    not decided, flagged for whoever builds the calibration step. Meanwhile
    only Strava rows populate `training_load` (9 of 251, all runs, stale since
    June — see CLAUDE.md), so most activities still contribute nothing here.
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
    the Banister impulse-response model, and the primary training-load-ratio
    signal in this system (see module docstring on why ACWR isn't). Standard
    exponential-decay recursive form:

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
