"""The readiness score composite — originally kickoff doc section 6, rebuilt
2026-08-30 against a real evidence review (ADR 0007) after Francisco asked
for the whole architecture to be re-derived from research rather than kept
as originally specced.

Pure function, deterministic, hand-verifiable (design principle 9, section 12).

**Not "computed alongside Garmin's own Training Readiness" — confirmed
permanently false, not just currently unbuilt.** That was the original
kickoff-doc framing; investigated directly against Francisco's real account
(see CLAUDE.md's "Garmin live sync built" section, 2026-08-28) and confirmed
his hardware (a Forerunner 165) never computes Training Readiness at all — a
deliberate Garmin device-tier limitation (market segmentation, not a
history-length gap this project could wait out), corroborated by Garmin's own
manuals, Garmin's own community forum, and an independent device-support
tracker. `daily_metrics.training_readiness` will stay permanently NULL on
this account's current hardware, so there is no Garmin composite to compare
against or disagree with. This project's own score is the only readiness
composite that exists for Francisco unless the watch changes.

Deliberately takes already-computed component values, not raw observation
histories — callers get those from `metrics/baselines.py`
(`compute_hrv_baseline`, `compute_rhr_baseline`, `compute_sleep_debt`), plus
`subjective_log.hooper_index` directly. Keeps this function single-purpose:
combine signals, don't compute them.

**ADR 0007 changed three things from the original kickoff-doc design**:
1. TSB/freshness is gone from this composite entirely (not just zero-weighted,
   which was the 2026-08-30 stopgap for a data-coverage bug) — real, if recent
   and narrow, 2025-2026 research argues same-day "readiness" and multi-week
   "training-stress state" are different constructs that shouldn't be fused
   into one number, and both Garmin's and WHOOP's own products keep them
   separate the same way this project's Training page already does. TSB stays
   a real, computed trend elsewhere (`metrics/load.py`, the structural
   `tsb_persistently_negative` trigger, the Training page) — just not folded
   into this score.
2. HRV/RHR deviation scoring gained a small "no real signal" dead zone before
   ADR 0006's quadratic curve starts moving the score at all — see
   `_deviation_to_score()`'s docstring.
3. `weight_subjective` raised from 0.10 to 0.25, absorbing TSB's freed 0.15 —
   see the weights dict below for the full reasoning.
"""

from __future__ import annotations

from typing import Any

# ADR 0007. Sums to 1.0 in the intended full model. Mirrored in
# config/athlete.yaml as the documented, tunable source of truth — kept here
# too as the function's default so it's independently testable without
# loading config.
#
# hrv/sleep/rhr unchanged from the original kickoff-doc split (no validated
# alternative weighting scheme exists anywhere — confirmed by deep research,
# not merely unfound — so there's nothing evidence-based to change these
# toward). tsb removed (see module docstring). subjective raised from the
# original 0.10 to 0.25 — the entirety of TSB's freed weight — because
# Saw, Main & Gastin 2016 (systematic review, 56 studies) found subjective
# wellness measures track training-load effects with sensitivity/consistency
# AT LEAST equal to, arguably better than, the objective measures they
# reviewed, while this composite had it weighted lowest of all five
# components. No literature number says "25" specifically — this is a
# reasoned, revisable default (same spirit as ADR 0006's exponent=2), chosen
# because reallocating one removed component's entire freed weight to the one
# component the evidence most directly supports raising is a simpler, more
# explicable rule than inventing a new split across all four survivors.
DEFAULT_READINESS_WEIGHTS = {
    "hrv": 0.35,
    "sleep": 0.25,
    "rhr": 0.15,
    "subjective": 0.25,
}

_HOOPER_INDEX_RANGE = (4.0, 40.0)  # best, worst — see core.models.SubjectiveLogEntry


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ADR 0006: the +-2 SD "full range" boundary is from the kickoff doc's own
# original spec ("clamped to +-2 SD") -- preserved exactly; only the SHAPE
# of the curve between 0 and the boundary changed, from linear to quadratic.
HRV_RHR_SD_CLAMP = 2.0

# ADR 0007: a small dead zone below which a deviation is treated as no real
# signal at all (flat 50, not just "dampened") rather than nudging the score
# even slightly. This is the "SWC/noise-floor gating" research verdict,
# layered on TOP of ADR 0006's quadratic curve rather than replacing it --
# Francisco chose (2026-08-30, asked directly rather than decided silently)
# to keep the existing 60-day population-SD baseline instead of rearchitecting
# to a shorter rolling window, so there's no per-athlete day-to-day
# coefficient-of-variation figure computed yet to anchor a personalized SWC
# (the Plews/Hopkins convention: ~0.5x the athlete's own trailing CV). Absent
# that, this uses Hopkins' generic population default instead: a smallest-
# worthwhile-change of ~0.2x SD -- and since `deviation_sd` here is already
# expressed in units of the 60-day population SD, that default is simply 0.2
# in these same units, no new baseline machinery required. Real precedent,
# not invented: Firstbeat's own disclosed HRV Recovery methodology (which
# partly underlies this project's Garmin data) already applies an SWC floor
# before scaling, and all three independent HRV-guided-training RCT programs
# found in the research use an SWC gate operationally. Whether this hybrid
# (gate-then-continuous) actually outperforms pure continuous scoring has
# never been tested head-to-head anywhere for this exact purpose -- adopting
# it is well-precedented engineering practice, not a proven-superior method.
HRV_RHR_NOISE_FLOOR_SD = 0.2


def _deviation_to_score(deviation_sd: float, *, invert: bool = False) -> float:
    """Maps a baseline deviation (in SD units) onto a 0-100 score: flat at 50
    within a small dead zone (+-0.2 SD, ADR 0007 -- "no real signal"), then a
    quadratic curve (ADR 0006) from the dead-zone edge out to the +-2 SD
    clamp boundary, still reaching the exact same 0/100 endpoints the
    original linear mapping did. An ordinary, statistically routine ~1 SD
    deviation (real data: roughly 1 day in 3) moves the score to ~40/60, not
    the 25/75 a straight linear mapping would give.

    Replaces a straight linear mapping (`50 + 25*clamp(x,-2,2)`) that spent
    a full quarter of the entire score range on the very first, routine SD
    of deviation -- real complaint, 2026-08-30: a 2bpm RHR blip with no
    sustained trend scored a 24/100, reading as a serious problem for
    something well within normal day-to-day noise.

    Researched before choosing this shape, not guessed (ADR 0006/0007 have
    the full synthesis): neither WHOOP nor Garmin discloses their actual
    formula (confirmed across official docs and a peer-reviewed cross-
    manufacturer survey that found NONE of 14 commercial composite scores
    disclose their weighting), and no peer-reviewed source validates any
    specific curve shape for this exact purpose. But real evidence
    supports THIS DIRECTION specifically: real device data shows day-to-
    day HRV noise is genuinely small relative to real training-driven
    shifts, and sports-science convention (Hopkins' "smallest worthwhile
    change," applied to HRV by Plews et al. and used operationally by
    every HRV-guided-training RCT program the ADR 0007 research found)
    already treats small deviations below a threshold as noise rather than
    signal at all. Critically, a sigmoid curve (the other common
    "nonlinear" shape, and what the one specific formula claiming to be
    WHOOP's actual math uses online -- self-described by its own author as
    an invented approximation, not a reverse-engineered fact) would move
    the score HARDER on ordinary noise than linear already does, the
    opposite of the goal -- verified by direct calculation before
    deciding, not assumed from the name "nonlinear." Only a power-law/
    quadratic-family curve delivers what was actually wanted; the specific
    exponent (2) and the specific dead-zone width (0.2 SD) both have no
    direct literature validation for this exact use and are documented,
    revisable defaults, same spirit as this project's other seed-phase
    numbers.

    `invert=True` for RHR: elevated RHR is LESS ready, the mirror image of
    HRV's "higher is better."
    """
    clamped = _clamp(deviation_sd, -HRV_RHR_SD_CLAMP, HRV_RHR_SD_CLAMP)
    span = HRV_RHR_SD_CLAMP - HRV_RHR_NOISE_FLOOR_SD
    magnitude = max(0.0, abs(clamped) - HRV_RHR_NOISE_FLOOR_SD)
    fraction = magnitude / span
    sign = -1.0 if clamped < 0 else 1.0
    delta = sign * 50.0 * fraction**2
    return 50.0 - delta if invert else 50.0 + delta


def _hrv_component_score(deviation_sd: float) -> float:
    """Higher HRV relative to baseline = more ready. Quadratic curve,
    clamped +-2 SD (ADR 0006) -- see `_deviation_to_score()`'s docstring
    for the full reasoning behind the shape.
    """
    return _deviation_to_score(deviation_sd)


def _rhr_component_score(deviation_sd: float) -> float:
    """Inverted vs HRV: elevated RHR relative to baseline = less ready.
    Same quadratic curve as HRV (ADR 0006).
    """
    return _deviation_to_score(deviation_sd, invert=True)


# ADR 0007: a single 8.0h point target contradicts the sleep-science
# consensus itself (the National Sleep Foundation's own adult recommendation
# is a 7-9h RANGE, deliberately not a point value) -- any night within this
# band now earns full quantity credit, rather than only exactly-8h doing so.
# Nothing above the band is penalized either (no evidence found that this
# population needs an upper-bound penalty for extra sleep). The lower edge
# (7.0) doubles as `metrics/baselines.py: DEFAULT_NIGHTLY_NEED_HOURS` for the
# rolling debt calculation -- kept as two independent constants in two
# modules (no shared import, same pattern as HRV_RHR_SD_CLAMP already being
# independent of anything in baselines.py), but conceptually the same number.
SLEEP_BAND_LOW_HOURS = 7.0

# ADR 0007: reduced from an even 50/50 blend (built 2026-08-28) after
# research found Garmin's own consumer sleep-stage classification -- the
# exact layer this quality score is built on -- scored WORST of 6 real
# devices independently validated against lab polysomnography (kappa=0.21,
# "fair," vs a same-device-generation company-reported 0.54), and the one
# athlete-specific study that directly compared duration vs. architecture
# (Knufinke et al. 2018, n=98 elite athletes) found duration significant and
# stage/efficiency measures NOT significant for next-day performance. Not
# removed entirely, though the evidence would support that -- Francisco
# specifically asked for REM/deep to be factored in (2026-08-30) and chose,
# when asked directly, to keep it at a reduced rather than zero weight, so
# the signal still counts, just not as an equal partner to duration+debt.
SLEEP_QUALITY_BLEND_WEIGHT = 0.25


def _sleep_component_score(
    last_night_hours: float | None,
    debt_hours: float | None,
    quality_score: float | None = None,
) -> float | None:
    """Blend of two halves: **quantity** (last night's duration vs a 7-9h
    band, combined with the 14-day rolling debt/surplus via `min()` — see
    below) and **quality** (Garmin's own `sleep_score`, which factors in
    REM/deep/restlessness/timing — something this project's own
    duration+debt math never looked at until Francisco asked directly,
    2026-08-30, why our sleep score read 97 the same night Garmin's read 74
    "Fair" for low REM), weighted at `SLEEP_QUALITY_BLEND_WEIGHT` rather than
    an even half (see that constant's docstring for why it's no longer
    50/50).

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
    duration_score = None
    if last_night_hours is not None:
        if last_night_hours >= SLEEP_BAND_LOW_HOURS:
            duration_score = 100.0
        else:
            duration_score = _clamp(last_night_hours / SLEEP_BAND_LOW_HOURS * 100.0, 0.0, 100.0)

    debt_score = None
    if debt_hours is not None:
        debt_score = _clamp(100.0 - debt_hours * 10.0, 0.0, 100.0)

    # ADR 0007 follow-up, 2026-08-31: this used to be a 50/50 AVERAGE of
    # duration_score and debt_score. Real trigger: a 5h50m night before an
    # early flight (Garmin's own quality score 64/100) landed a banked
    # 14-day surplus (debt_score ~100) averaged against the bad night
    # (duration_score ~83) into a quantity_score of ~91.65 -- a rolling
    # surplus effectively bought back most of a genuinely rough night's
    # score. Two real controlled studies that directly tested "banking"
    # sleep before subsequent restriction (Rupp et al. 2009, Sleep
    # 32(3):311-321; Arnal et al. 2015, Sleep 38(12):1935-1943) found the
    # advantage is real but PARTIAL, and "largely erased by day 3" -- no
    # study supports a surplus fully or near-fully offsetting a bad night's
    # score the way a symmetric average does. The two-process model of sleep
    # regulation (Borbely et al. 2016) gives the mechanistic reason: sleep
    # pressure builds/resets on a saturating curve, not a linear bank --
    # there's no real "reserve" a 13-day-old good night should still be
    # drawing down from today. Changed to `min()`: debt can only ever act as
    # a downward penalty (a real chronic deficit still correctly drags the
    # score down even on a night whose own duration was fine) or a neutral
    # pass-through -- never an upward credit that rescues a bad night. This
    # is the deliberately conservative choice: a more elaborate small-and-
    # decaying-credit alternative exists in principle (mirroring WHOOP's own
    # patent-disclosed, continuously-decaying debt shape) but has no specific
    # magnitude or decay window validated by anything found in this research
    # pass, so it isn't built -- `min()` needs no new invented parameter.
    if duration_score is not None and debt_score is not None:
        quantity_score = min(duration_score, debt_score)
    elif duration_score is not None:
        quantity_score = duration_score
    elif debt_score is not None:
        quantity_score = debt_score
    else:
        quantity_score = None

    if quantity_score is None:
        return quality_score
    if quality_score is None:
        return quantity_score
    w = SLEEP_QUALITY_BLEND_WEIGHT
    return quantity_score * (1.0 - w) + quality_score * w


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
        # weight 0.0 in `weights` (e.g. a future component whose inputs are
        # known unreliable, same reasoning TSB itself used briefly in
        # 2026-08-30 before ADR 0007 removed it from this composite outright)
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
