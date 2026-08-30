"""The readiness score composite (kickoff doc section 6).

Pure function, deterministic, hand-verifiable (design principle 9, section 12).
Computed alongside Garmin's own Training Readiness so disagreement is visible
— this is Francisco's own composite, not a replacement for Garmin's.

Deliberately takes already-computed component values, not raw observation
histories — callers get those from `metrics/baselines.py`
(`compute_hrv_baseline`, `compute_rhr_baseline`, `compute_sleep_debt`) and
`metrics/load.py` (`compute_tsb_zscore`), plus `subjective_log.hooper_index`
directly. Keeps this function single-purpose: combine signals, don't compute
them.
"""

from __future__ import annotations

from typing import Any

# Kickoff doc section 6. Mirrored in config/athlete.yaml as the documented
# source of truth for these numbers — kept here too as the function's default
# so it's independently testable without loading config.
DEFAULT_READINESS_WEIGHTS = {
    "hrv": 0.35,
    "sleep": 0.25,
    "rhr": 0.15,
    "tsb": 0.15,
    "subjective": 0.10,
}

_HOOPER_INDEX_RANGE = (4.0, 40.0)  # best, worst — see core.models.SubjectiveLogEntry


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _hrv_component_score(deviation_sd: float) -> float:
    """Higher HRV relative to baseline = more ready. Clamped +-2 SD."""
    return 50.0 + 25.0 * _clamp(deviation_sd, -2.0, 2.0)


def _rhr_component_score(deviation_sd: float) -> float:
    """Inverted vs HRV: elevated RHR relative to baseline = less ready."""
    return 50.0 - 25.0 * _clamp(deviation_sd, -2.0, 2.0)


def _sleep_component_score(
    last_night_hours: float | None,
    debt_hours: float | None,
    quality_score: float | None = None,
    *,
    need_hours: float = 8.0,
) -> float | None:
    """Blend of two halves: **quantity** (last night's duration vs need,
    50/50 with the 14-day rolling debt — the kickoff doc doesn't specify an
    exact split, a documented default, not a given number) and **quality**
    (Garmin's own `sleep_score`, which factors in REM/deep/restlessness/
    timing — something this project's own duration+debt math never looked
    at until Francisco asked directly, 2026-08-30, why our sleep score read
    97 the same night Garmin's read 74 "Fair" for low REM).

    Deliberately reuses Garmin's own quality algorithm rather than inventing
    a stage-weighting formula from raw deep/light/rem/awake minutes — Garmin
    already does real, tuned quality scoring on the same underlying data;
    re-deriving a worse approximation of it would be reinventing something
    already measured, not adding real information.

    Quality is optional and additive, never required: quantity alone is
    still returned when `quality_score` is `None` (a day/source without a
    Garmin sleep score), so this stays exactly backward-compatible rather
    than a hard new dependency. Returns `None` only when there is truly
    nothing to build any of this from.
    """
    quantity_parts = []
    if last_night_hours is not None:
        quantity_parts.append(_clamp(last_night_hours / need_hours * 100.0, 0.0, 100.0))
    if debt_hours is not None:
        quantity_parts.append(_clamp(100.0 - debt_hours * 10.0, 0.0, 100.0))
    quantity_score = sum(quantity_parts) / len(quantity_parts) if quantity_parts else None

    if quantity_score is None:
        return quality_score
    if quality_score is None:
        return quantity_score
    return (quantity_score + quality_score) / 2.0


def _tsb_component_score(z_score: float) -> float:
    """Higher TSB (fresher than usual) = more ready. Clamped +-2 like HRV."""
    return 50.0 + 25.0 * _clamp(z_score, -2.0, 2.0)


def _subjective_component_score(hooper_index: float) -> float:
    """hooper_index is 4 (excellent) to 40 (terrible) by construction — lower
    is better, so this inverts linearly onto a 0-100 "more ready" scale.
    """
    lo, hi = _HOOPER_INDEX_RANGE
    fraction = (hooper_index - lo) / (hi - lo)
    return _clamp(100.0 - fraction * 100.0, 0.0, 100.0)


def compute_readiness_score(
    *,
    hrv_deviation_sd: float | None = None,
    rhr_deviation_sd: float | None = None,
    last_night_sleep_hours: float | None = None,
    sleep_debt_hours: float | None = None,
    sleep_quality_score: float | None = None,
    tsb_z_score: float | None = None,
    hooper_index: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """0-100 readiness composite. Never a black box: always returns every
    component's raw input, its 0-100 sub-score, and the weight actually used.

    Missing components are NOT invented as a neutral 50 — they're dropped, and
    the remaining components' weights are renormalized to sum to 1.0.
    `coverage` reports what fraction of the full weight was backed by real
    data, so a score built from 2 of 5 components reads as visibly less
    trustworthy than one built from all 5, not silently identical to it.
    """
    weights = weights or DEFAULT_READINESS_WEIGHTS

    components: dict[str, dict[str, Any]] = {}

    if hrv_deviation_sd is not None:
        components["hrv"] = {
            "raw": hrv_deviation_sd,
            "score": _hrv_component_score(hrv_deviation_sd),
        }
    if rhr_deviation_sd is not None:
        components["rhr"] = {
            "raw": rhr_deviation_sd,
            "score": _rhr_component_score(rhr_deviation_sd),
        }
    sleep_score = _sleep_component_score(
        last_night_sleep_hours, sleep_debt_hours, sleep_quality_score
    )
    if sleep_score is not None:
        components["sleep"] = {
            "raw": {
                "last_night_hours": last_night_sleep_hours,
                "debt_hours": sleep_debt_hours,
                "quality_score": sleep_quality_score,
            },
            "score": sleep_score,
        }
    if tsb_z_score is not None:
        components["tsb"] = {"raw": tsb_z_score, "score": _tsb_component_score(tsb_z_score)}
    if hooper_index is not None:
        components["subjective"] = {
            "raw": hooper_index,
            "score": _subjective_component_score(hooper_index),
        }

    if not components:
        return {"score": None, "components": {}, "coverage": 0.0, "confidence": "insufficient_data"}

    covered_weight = sum(weights[name] for name in components)
    if covered_weight <= 0.0:
        # Every component that actually has data today was configured with
        # weight 0.0 (e.g. `weight_tsb: 0.0` while its inputs are known stale)
        # -- renormalizing a real weight against zero total weight is
        # undefined, not almost-zero, so this is "no usable score" the same
        # as the empty-components case above, not a crash.
        return {
            "score": None,
            "components": components,
            "coverage": 0.0,
            "confidence": "insufficient_data",
        }
    total = 0.0
    for name, comp in components.items():
        normalized_weight = weights[name] / covered_weight
        comp["weight_used"] = normalized_weight
        total += comp["score"] * normalized_weight

    return {
        "score": round(total, 1),
        "components": components,
        "coverage": covered_weight,
        "confidence": "full" if covered_weight >= 0.99 else "partial",
    }
