"""VO2max: the last real Garmin measurement, plus a personally-calibrated
estimate for the time since -- built 2026-10-06 for an athlete who no longer
runs (permanent knee guardrail) and has no cycling power meter, so Garmin
will never produce a new reading on current hardware.

Researched before building (research agent, 2026-10-06, every citation
checked against its PubMed record):

- The resting-HR ratio method (Uth et al. 2004, PMID 14624296: VO2max ~=
  15.3 x HRmax/HRrest) is the only resting-data method with a usable error
  in trained men (SEE ~2.7 ml/kg/min) -- but the 15.3 factor came from 10
  people, an independent test found 14.6 +- 2.6 (Castagna et al. 2022, PMID
  35301581), and both used SUPINE, rested HR. A wearable's daily minimum RHR
  runs lower, which biases the raw formula high: on this account's own June
  data it gives 57.1 against Garmin's measured 53.
- So the generic 15.3 is replaced by a PERSONAL factor fitted to this
  athlete's own Garmin measurements (the between-person spread Castagna
  found is exactly what a personal factor removes), and the estimate tracks
  the 28-day median RHR from there.
- Within-person RHR change tracks VO2max change only weakly (closest
  analogue: individual-change r=0.37, Hansen et al. 2025, PMID 39833426) and
  RHR also falls for non-fitness reasons (energy deficit, heat, sleep) -- so
  the uncertainty band is deliberately wide and widens with time since the
  last real measurement, the number is capped near the anchor, and it is
  hidden entirely after 26 weeks rather than shown as if it still meant
  something.
- No validated method turns heart rate WITHOUT a known workload (speed or
  power) into VO2max -- so BJJ heart rate and bike speed are never inputs.
  `bjj_rest_recovery()` is returned as context only. HRV is context only too
  (its link to fitness is bidirectional and saturates, Plews et al. 2013).

Constants below are the research's reasoned defaults, not literature values,
except SIGMA_ANCHOR_ML (Garmin's exercise-based estimates carry ~5-7% error
vs lab tests, ~3.5 ml/kg/min at this level -- Molina-Garcia et al. 2022
meta-analysis, PMID 35072942; device studies PMID 39797066, 42822520).
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Any

RHR_WINDOW_DAYS = 28
RHR_MIN_READINGS = 14  # a 28-day median off fewer real nights isn't stable
SIGMA_ANCHOR_ML = 3.5  # error of the Garmin measurement itself
# Reasoned default, no literature value: ~a third of Coyle et al. 1984's
# complete-cessation decline (~1 ml/kg/min/week, PMID 6511559), since BJJ +
# bike training continues (reduced training preserves VO2max when intensity
# is kept -- Mujika & Padilla 2000, PMID 10966148).
DRIFT_ML_PER_WEEK = 0.3
CLAMP_LOW_FRACTION = 0.84  # Coyle's -16% plateau after full detraining
CLAMP_HIGH_FRACTION = 1.10
LOW_CONFIDENCE_AFTER_WEEKS = 12
HIDE_AFTER_WEEKS = 26
ESTIMATE_SERIES_STEP_DAYS = 7
# Andreato et al. 2017 systematic review of BJJ athletes (PMID 28194734).
BJJ_REFERENCE_RANGE = (42.0, 52.0)
# A rest shorter than this is a truncated tail, not a real between-round rest.
MIN_REST_DURATION_S = 55.0


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def rolling_rhr_median(
    rhr_obs: list[tuple[str, float]],
    as_of: str,
    window_days: int = RHR_WINDOW_DAYS,
    min_readings: int = RHR_MIN_READINGS,
) -> float | None:
    """Median resting HR over the `window_days` ending on `as_of` (inclusive).
    `None` below `min_readings` real nights -- never a median of a handful."""
    start = _shift(as_of, -(window_days - 1))
    values = [v for d, v in rhr_obs if start <= d <= as_of]
    if len(values) < min_readings:
        return None
    return float(statistics.median(values))


def _window_mean(obs: list[tuple[str, float]], as_of: str, window_days: int) -> float | None:
    start = _shift(as_of, -(window_days - 1))
    values = [v for d, v in obs if start <= d <= as_of]
    return sum(values) / len(values) if values else None


def calibrate_personal_factor(
    vo2_obs: list[tuple[str, float]], rhr_obs: list[tuple[str, float]], hr_max: float
) -> dict[str, Any] | None:
    """Fits this athlete's own factor in VO2max = factor x HRmax / RHR_28d.

    One anchor per real Garmin measurement that has a usable 28-day RHR
    median behind it; the factor is their mean. `sigma_cal` is the spread of
    the anchors' residuals (measured minus what the fitted factor predicts)
    in ml/kg/min -- how well one personal factor actually fits this person.
    With a single anchor there's no spread to measure, so it falls back to
    SIGMA_ANCHOR_ML rather than claiming a perfect fit. `None` if no
    measurement has RHR data around it.
    """
    anchors = []
    for day, vo2 in vo2_obs:
        rhr = rolling_rhr_median(rhr_obs, day)
        if rhr is None:
            continue
        anchors.append({"date": day, "vo2max": vo2, "rhr_28d": rhr, "factor": vo2 * rhr / hr_max})
    if not anchors:
        return None
    factor = sum(a["factor"] for a in anchors) / len(anchors)
    for a in anchors:
        a["predicted"] = factor * hr_max / a["rhr_28d"]
    residuals = [a["vo2max"] - a["predicted"] for a in anchors]
    sigma_cal = statistics.pstdev(residuals) if len(anchors) >= 2 else SIGMA_ANCHOR_ML
    return {"factor": factor, "sigma_cal": sigma_cal, "n_anchors": len(anchors), "anchors": anchors}


def estimate_on(
    day: str,
    vo2_obs: list[tuple[str, float]],
    rhr_obs: list[tuple[str, float]],
    hr_max: float,
    calibration: dict[str, Any] | None,
) -> dict[str, Any]:
    """The VO2max read for one date. Status is one of:

    - `measured`: a real Garmin reading exists on this exact date.
    - `estimate` / `low_confidence`: calibrated from RHR, with a ±1 sigma
      likely range; low confidence after LOW_CONFIDENCE_AFTER_WEEKS since
      the last real measurement.
    - `too_old`: more than HIDE_AFTER_WEEKS since the last measurement --
      no number at all.
    - `insufficient_data`: no prior measurement, no calibration, or not
      enough recent RHR nights.
    """
    prior = [(d, v) for d, v in vo2_obs if d <= day]
    if not prior:
        return {"date": day, "status": "insufficient_data", "value": None}
    anchor_date, anchor_value = prior[-1]
    if anchor_date == day:
        return {"date": day, "status": "measured", "value": anchor_value}

    weeks = (date.fromisoformat(day) - date.fromisoformat(anchor_date)).days / 7.0
    base = {"date": day, "anchor_date": anchor_date, "anchor_value": anchor_value}
    base["weeks_since_anchor"] = round(weeks, 1)
    if weeks > HIDE_AFTER_WEEKS:
        return {**base, "status": "too_old", "value": None}
    rhr = rolling_rhr_median(rhr_obs, day)
    if calibration is None or rhr is None:
        return {**base, "status": "insufficient_data", "value": None}

    raw = calibration["factor"] * hr_max / rhr
    low_cap, high_cap = anchor_value * CLAMP_LOW_FRACTION, anchor_value * CLAMP_HIGH_FRACTION
    value = min(max(raw, low_cap), high_cap)
    sigma = math.sqrt(
        SIGMA_ANCHOR_ML**2 + calibration["sigma_cal"] ** 2 + (DRIFT_ML_PER_WEEK * weeks) ** 2
    )
    status = "low_confidence" if weeks > LOW_CONFIDENCE_AFTER_WEEKS else "estimate"
    return {
        **base,
        "status": status,
        "value": round(value, 1),
        "low": round(value - sigma, 1),
        "high": round(value + sigma, 1),
        "sigma": round(sigma, 1),
        "rhr_28d": rhr,
        "clamped": value != raw,
    }


def bjj_rest_recovery(segments: list[dict[str, Any]]) -> float | None:
    """Mean heart-rate drop from each round to the full rest that follows it,
    for one auto-segmented BJJ session (`activity_auto_segments` rows, in
    order). Context only -- never a VO2max input: the drop depends on how
    hard the preceding round was, which isn't controlled (Daanen et al.
    2012, PMID 22357753), so it's only comparable across similar sessions.
    `None` if no complete round->rest pair exists."""
    drops = []
    for prev, seg in zip(segments, segments[1:], strict=False):
        if (
            prev["label"] == "round"
            and seg["label"] == "rest"
            and prev["avg_hr"] is not None
            and seg["avg_hr"] is not None
            and seg["end_s"] - seg["start_s"] >= MIN_REST_DURATION_S
        ):
            drops.append(prev["avg_hr"] - seg["avg_hr"])
    return round(sum(drops) / len(drops), 1) if drops else None


def _meaning(
    current: dict[str, Any], latest: tuple[str, float] | None, as_of: str
) -> dict[str, Any]:
    if latest is None:
        return {"tone": "unknown", "headline": "No real VO2max measurement on record yet."}
    anchor_date, anchor_value = latest
    days = (date.fromisoformat(as_of) - date.fromisoformat(anchor_date)).days
    measured = f"Last measured {anchor_value:.0f} on {anchor_date} ({days} days ago)."
    status = current["status"]
    if status == "measured":
        return {"tone": "neutral", "headline": f"Measured {anchor_value:.0f} today."}
    if status == "too_old":
        return {
            "tone": "unknown",
            "headline": (
                f"{measured} That's too long ago to estimate from — "
                "it needs a new real measurement."
            ),
        }
    if status == "insufficient_data":
        return {
            "tone": "unknown",
            "headline": f"{measured} Not enough recent resting heart rate data to estimate since.",
        }
    caveat = (
        " A lower resting heart rate during a weight cut isn't proof of getting fitter, "
        'so read this as "maintained", not "improved".'
        if current["value"] > anchor_value
        else ""
    )
    confidence = (
        " Low confidence this long after the last measurement."
        if status == "low_confidence"
        else ""
    )
    return {
        "tone": "neutral",
        "headline": (
            f"{measured} Based on your resting heart rate since, it's most likely held around "
            f"{current['value']:.0f} (likely range "
            f"{current['low']:.0f}–{current['high']:.0f}).{caveat}{confidence}"
        ),
    }


def build_vo2max_summary(
    vo2_obs: list[tuple[str, float]],
    rhr_obs: list[tuple[str, float]],
    hrv_obs: list[tuple[str, float]],
    weight_ewma: list[tuple[str, float]],
    hr_max: float,
    as_of: str,
) -> dict[str, Any]:
    """Everything the VO2max section shows, bounded to `as_of` (no future
    rows leak in). All observation lists are (date, value), ascending."""
    vo2_obs = [(d, v) for d, v in vo2_obs if d <= as_of]
    rhr_obs = [(d, v) for d, v in rhr_obs if d <= as_of]
    hrv_obs = [(d, v) for d, v in hrv_obs if d <= as_of]
    weight_ewma = [(d, v) for d, v in weight_ewma if d <= as_of]

    calibration = calibrate_personal_factor(vo2_obs, rhr_obs, hr_max)
    current = estimate_on(as_of, vo2_obs, rhr_obs, hr_max, calibration)
    latest = vo2_obs[-1] if vo2_obs else None

    # The estimate only fills the gap AFTER the last real measurement --
    # between real readings the measurements speak for themselves, and the
    # (loose, sigma_cal ~3) personal fit would just draw a second, worse line
    # through the same period.
    estimate_series = []
    if vo2_obs:
        day = vo2_obs[-1][0]
        while day <= as_of:
            point = estimate_on(day, vo2_obs, rhr_obs, hr_max, calibration)
            if point["status"] in ("estimate", "low_confidence"):
                estimate_series.append(
                    {k: point[k] for k in ("date", "value", "low", "high", "status")}
                )
            day = _shift(day, ESTIMATE_SERIES_STEP_DAYS)
        if current["status"] in ("estimate", "low_confidence") and (
            not estimate_series or estimate_series[-1]["date"] != as_of
        ):
            estimate_series.append(
                {k: current[k] for k in ("date", "value", "low", "high", "status")}
            )

    # Weight-only effect: ml/kg/min rises as weight falls with no change in
    # fitness at all -- shown separately so a cut isn't mistaken for a gain.
    weight_only = None
    if latest is not None and weight_ewma:
        at_anchor = [v for d, v in weight_ewma if d <= latest[0]]
        if at_anchor:
            weight_only = {
                "value": round(latest[1] * at_anchor[-1] / weight_ewma[-1][1], 1),
                "weight_at_anchor_kg": round(at_anchor[-1], 1),
                "weight_now_kg": round(weight_ewma[-1][1], 1),
            }

    context: dict[str, Any] = {"bjj_reference_range": list(BJJ_REFERENCE_RANGE)}
    if latest is not None:
        context["rhr_28d_at_anchor"] = rolling_rhr_median(rhr_obs, latest[0])
        hrv_anchor = _window_mean(hrv_obs, latest[0], RHR_WINDOW_DAYS)
        context["hrv_28d_at_anchor"] = round(hrv_anchor, 1) if hrv_anchor is not None else None
    context["rhr_28d_now"] = rolling_rhr_median(rhr_obs, as_of)
    hrv_now = _window_mean(hrv_obs, as_of, RHR_WINDOW_DAYS)
    context["hrv_28d_now"] = round(hrv_now, 1) if hrv_now is not None else None

    return {
        "as_of": as_of,
        "hr_max": hr_max,
        "latest_measurement": (
            {
                "date": latest[0],
                "value": latest[1],
                "days_ago": (date.fromisoformat(as_of) - date.fromisoformat(latest[0])).days,
            }
            if latest
            else None
        ),
        "current": current,
        "measurements": [{"date": d, "value": v} for d, v in vo2_obs],
        "estimate_series": estimate_series,
        "calibration": (
            {
                "personal_factor": round(calibration["factor"], 2),
                "sigma_cal": round(calibration["sigma_cal"], 2),
                "n_anchors": calibration["n_anchors"],
                "anchors": [
                    {
                        "date": a["date"],
                        "vo2max": a["vo2max"],
                        "rhr_28d": a["rhr_28d"],
                        "predicted": round(a["predicted"], 1),
                    }
                    for a in calibration["anchors"]
                ],
            }
            if calibration
            else None
        ),
        "weight_only": weight_only,
        "context": context,
        "meaning": _meaning(current, latest, as_of),
    }
