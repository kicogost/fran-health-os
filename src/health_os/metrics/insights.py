"""Plain-language trend insights for the Trends page (2026-08-30).

Francisco, looking at the raw charts: "you need to tell me things you see
in trends from the data... no fluff no acronyms." This module turns
already-computed baseline/trend results (from `metrics/baselines.py`,
`metrics/body_comp.py`, `metrics/correlations.py`) into short, plain-English
sentences a non-expert can read in one glance.

Same discipline as `coach/rules.py`: every sentence here is a fixed template
selected by a real computed number — never freeform generation, no LLM call
(design principle 6/section 12 — "language generation happens only in the
briefing layer, from rules-engine output" applies just as much here as it
does to the daily coaching briefing). Pure functions, no DB access — callers
in `api/trends.py` do the fetching/windowing and pass in already-computed
results, mirroring how `coach/briefing.py` calls `coach/rules.py`.

Every insight is `{"metric", "tone", "headline", "detail"}` — `tone` is one
of "good"/"neutral"/"bad"/"unknown" (never invented when there isn't enough
data: "unknown" is a real, honest state, not silently "neutral"), `headline`
is the one-sentence takeaway, `detail` is an optional second sentence with
supporting context (or `None` when there's nothing more useful to add).
"""

from __future__ import annotations

from typing import Any


def _fmt_hours_minutes(hours: float) -> str:
    total_min = round(hours * 60)
    h, m = divmod(total_min, 60)
    return f"{h}h{m:02d}m"


def weight_insight(
    trend: dict[str, Any], comp_countdown: dict[str, Any] | None = None
) -> dict[str, Any]:
    """From `body_comp.weight_trend_ols()`'s 21-day OLS slope + 95% CI.
    "Distinguishable from flat" means the CI doesn't straddle zero — the
    same honesty this project's weight-trend work has used since Phase 4
    (kickoff doc section 6: "the noise is comparable to the signal").
    """
    if trend.get("confidence") != "full" or trend.get("slope_kg_per_week") is None:
        return {
            "metric": "weight",
            "tone": "unknown",
            "headline": "Not enough recent weigh-ins to see a trend yet.",
            "detail": "Log a few more and this fills in on its own.",
        }

    slope = trend["slope_kg_per_week"]
    ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
    distinguishable = not (ci_low <= 0 <= ci_high)
    rate = abs(slope)

    if not distinguishable:
        headline = "Your weight has been holding steady over the last 3 weeks."
        tone = "neutral"
    elif slope < 0:
        headline = f"You're losing weight — down about {rate:.1f}kg/week over the last 3 weeks."
        tone = "good"
    else:
        headline = f"You've been gaining weight — up about {rate:.1f}kg/week over the last 3 weeks."
        tone = "bad"

    detail = None
    if comp_countdown is not None:
        if comp_countdown.get("red_flag"):
            detail = (
                "At this rate you won't make weight in time — the pace needed from here is "
                "faster than what's safe for a fat-loss cut alone."
            )
        elif distinguishable and slope < 0:
            detail = "That's on track for your competition weight."

    return {"metric": "weight", "tone": tone, "headline": headline, "detail": detail}


def sleep_insight(
    debt: dict[str, Any],
    this_week_avg_hours: float | None,
    last_week_avg_hours: float | None,
) -> dict[str, Any]:
    """From `baselines.compute_sleep_debt()`'s rolling 14-day debt (positive
    = deficit, negative = surplus vs. the 7h floor) plus a plain week-over-
    week average comparison for real direction of change.
    """
    if debt.get("confidence") == "insufficient_data" or debt.get("debt_hours") is None:
        return {
            "metric": "sleep",
            "tone": "unknown",
            "headline": "Not enough recent sleep data to tell yet.",
            "detail": None,
        }

    debt_hours = debt["debt_hours"]
    if debt_hours <= -3.0:
        state, tone = "You're sleeping great", "good"
    elif debt_hours <= 3.0:
        state, tone = "Your sleep has been about right", "neutral"
    else:
        state, tone = "You've been under-sleeping", "bad"

    if this_week_avg_hours is not None:
        headline = (
            f"{state} — averaging {_fmt_hours_minutes(this_week_avg_hours)} a night this week."
        )
    else:
        headline = f"{state} over the last 2 weeks."

    detail = None
    if this_week_avg_hours is not None and last_week_avg_hours is not None:
        diff = this_week_avg_hours - last_week_avg_hours
        if abs(diff) >= 0.5:
            direction = "up" if diff > 0 else "down"
            detail = (
                f"That's {direction} from last week's {_fmt_hours_minutes(last_week_avg_hours)}."
            )

    return {"metric": "sleep", "tone": tone, "headline": headline, "detail": detail}


def hrv_insight(baseline: dict[str, Any]) -> dict[str, Any]:
    """From `baselines.compute_hrv_baseline()` — only speaks once the real
    60-day computed baseline exists (`confidence == "full"`), never off the
    provisional seed-phase thresholds, since those are placeholders, not a
    real personal baseline yet.

    Headlines say "your recovery signal" rather than the acronym "HRV" — a
    real gap found 2026-08-31: every branch here still literally said "HRV,"
    inconsistent with `rhr_insight()` below, which correctly spells out
    "resting heart rate" instead of "RHR." Same "no fluff no acronyms" ask
    that already drove the rest of this module.
    """
    if baseline.get("confidence") != "full":
        return {
            "metric": "hrv",
            "tone": "unknown",
            "headline": "Still building your recovery-signal baseline (needs 60 days of history).",
            "detail": None,
        }

    status = baseline["status"]
    value = baseline["value"]
    if status == "high":
        headline = (
            f"Your recovery signal has been above your normal range lately ({value:.0f}ms) — "
            "a good recovery sign."
        )
        tone = "good"
    elif status == "low":
        headline = (
            f"Your recovery signal has been below your normal range lately ({value:.0f}ms) — "
            "you may need more recovery."
        )
        tone = "bad"
    else:
        headline = f"Your recovery signal has been right around normal ({value:.0f}ms)."
        tone = "neutral"

    return {"metric": "hrv", "tone": tone, "headline": headline, "detail": None}


def rhr_insight(baseline: dict[str, Any]) -> dict[str, Any]:
    """From `baselines.compute_rhr_baseline()` — direction is INVERTED vs.
    HRV (a lower resting heart rate than your own normal is the good sign).
    """
    if baseline.get("confidence") != "full":
        return {
            "metric": "rhr",
            "tone": "unknown",
            "headline": "Still building your resting-heart-rate baseline.",
            "detail": None,
        }

    status = baseline["status"]
    value = baseline["value"]
    sustained = baseline.get("sustained_rise_flag")

    if status == "high":
        headline = f"Your resting heart rate has been a bit elevated lately ({value:.0f}bpm)."
        tone = "bad"
        detail = (
            "That's held for 3 days running — worth an easier day or two." if sustained else None
        )
    elif status == "low":
        headline = (
            f"Your resting heart rate has been lower than usual ({value:.0f}bpm) — a good sign."
        )
        tone = "good"
        detail = None
    else:
        headline = f"Your resting heart rate has been steady ({value:.0f}bpm)."
        tone = "neutral"
        detail = None

    return {"metric": "rhr", "tone": tone, "headline": headline, "detail": detail}


# Plain-English versions of metrics/correlations.py's own (still fairly
# technical) `description` field, keyed the same way `_CANDIDATE_PAIRS` is.
# Kept here, not in correlations.py, since that module's own docstring is
# explicit it stays a pure stats engine — narration is this module's job.
_PLAIN_PAIR_TEXT = {
    (
        "sleep_quality",
        "hrv_overnight_ms",
    ): "how well you say you slept tracks your measured overnight HRV",
    ("stress", "resting_hr"): "your subjective stress tracks your measured resting heart rate",
    ("fatigue", "sleep_total_min"): "how tired you feel tracks how much you actually sleep",
    (
        "hooper_index",
        "readiness_score",
    ): "your daily wellness check-in tracks the computed readiness score",
}

# Fields stored on a "lower = better" scale -- sleep_quality (1=best..10=worst)
# and hooper_index (4=excellent..40=terrible, migration 0002) -- the OPPOSITE
# of how their `_PLAIN_PAIR_TEXT` descriptions above naturally read to an
# English reader ("how well you say you slept," "your daily wellness
# check-in," both read as "higher = better"). Real bug found 2026-08-31: the
# direction sentence below used to be worded straight off `rho`'s raw sign,
# so a genuine inverse relationship between sleep_quality and HRV (the
# physiologically correct direction -- a WORSE sleep_quality score, i.e. a
# LOWER number, goes with a HIGHER HRV) rendered as "when one goes up, the
# other tends to go down," which reads backwards to an English reader
# ("better sleep -> worse HRV," the opposite of the true finding).
# Normalizing the sign here (once per inverted-polarity field in the pair,
# so two inverted fields cancel out) makes the direction wording correct
# regardless of a field's underlying storage polarity -- picked over
# rewording `_PLAIN_PAIR_TEXT` itself since it protects any future pair
# added to `metrics/correlations.py: _CANDIDATE_PAIRS` too, not just these
# two known ones today.
_INVERTED_POLARITY_FIELDS = {"sleep_quality", "hooper_index"}


def _plain_language_rho(rho: float, x_name: str | None, y_name: str | None) -> float:
    """`rho`, re-signed so its direction always matches how an English
    reader would parse the pair's plain-language description (see
    `_INVERTED_POLARITY_FIELDS`'s docstring above) -- used only to choose the
    direction sentence's wording, never as a replacement for the real,
    reported `rho` (which stays exactly what `metrics/correlations.py`
    computed, for anyone checking the math).
    """
    sign = 1.0
    if x_name in _INVERTED_POLARITY_FIELDS:
        sign *= -1.0
    if y_name in _INVERTED_POLARITY_FIELDS:
        sign *= -1.0
    return rho * sign


FITNESS_TREND_LOOKBACK_DAYS = 21
FITNESS_TREND_MIN_HISTORY_DAYS = 14
# A relative move smaller than this reads as noise around the same EWMA
# level, not a real trend -- a reasoned, documented default (no literature
# number exists for "how much CTL change is meaningful to a person," same
# spirit as this project's other seed-phase constants), chosen because
# CTL's own 42-day time constant means small day-to-day wiggles are
# expected and shouldn't be over-read as "your fitness is changing."
FITNESS_TREND_RELATIVE_THRESHOLD = 0.15


def fitness_trend_insight(ctl_series: list[tuple[str, float]]) -> dict[str, Any]:
    """Plain-language reframing of CTL (Banister's "fitness," metrics/
    load.py) — never shown as a raw number or the term "CTL" itself
    (Francisco: "no fluff no acronyms"). Compares today's value against
    ~`FITNESS_TREND_LOOKBACK_DAYS` ago rather than showing the absolute
    level, since CTL's own units aren't meaningful on their own (ADR 0008 —
    TRIMP-based, not on any universally comparable scale).
    """
    if len(ctl_series) < FITNESS_TREND_MIN_HISTORY_DAYS:
        return {
            "metric": "fitness_trend",
            "tone": "unknown",
            "headline": "Not enough training history yet to see a fitness trend.",
            "detail": None,
        }

    latest = ctl_series[-1][1]
    lookback_idx = max(0, len(ctl_series) - 1 - FITNESS_TREND_LOOKBACK_DAYS)
    baseline = ctl_series[lookback_idx][1]
    rel_change = 0.0 if baseline <= 0 else (latest - baseline) / baseline

    if rel_change > FITNESS_TREND_RELATIVE_THRESHOLD:
        return {
            "metric": "fitness_trend",
            "tone": "good",
            "headline": "Your fitness has been building over the last few weeks.",
            "detail": None,
        }
    if rel_change < -FITNESS_TREND_RELATIVE_THRESHOLD:
        return {
            "metric": "fitness_trend",
            "tone": "neutral",
            "headline": "Your fitness has dipped a bit — you've trained less than a few weeks ago.",
            "detail": "Normal during a lighter week or a taper; worth a look if it wasn't planned.",
        }
    return {
        "metric": "fitness_trend",
        "tone": "neutral",
        "headline": "Your fitness has been holding steady over the last few weeks.",
        "detail": None,
    }


# Self-relative bands (z-score of latest TSB vs. its own trailing 90-day
# distribution, metrics/load.py: compute_tsb_zscore()) — never an absolute
# TSB threshold, since raw TSB magnitude has no universally validated
# "good"/"bad" cutoff (ADR 0003/0007). Boundaries are a reasoned,
# documented default (no literature number exists for this specific
# banding), chosen to roughly match "notably outside your normal range"
# (|z|>1.5) vs. "a bit off" (|z|>0.5) vs. "normal" -- same spirit as this
# project's other self-relative HRV/RHR scoring.
FRESHNESS_BANDS: list[tuple[float, str, str, str]] = [
    (-1.5, "fatigued", "bad", "You're carrying more fatigue than usual right now."),
    (-0.5, "tired", "neutral", "You're a little more tired than usual."),
    (0.5, "normal", "neutral", "You're about as fresh as usual."),
    (1.5, "fresh", "good", "You're fresher than usual."),
]


def freshness_insight(tsb_zscore: dict[str, Any]) -> dict[str, Any]:
    """Plain-language reframing of TSB (Banister's "freshness"/"form") — a
    banded, self-relative read rather than the raw z-score or the term
    "TSB" itself.
    """
    if tsb_zscore.get("confidence") != "full" or tsb_zscore.get("z_score") is None:
        return {
            "metric": "freshness",
            "tone": "unknown",
            "headline": "Not enough training history yet to tell how fresh you are.",
            "detail": None,
            "band": "unknown",
        }

    z = tsb_zscore["z_score"]
    for upper, band, tone, headline in FRESHNESS_BANDS:
        if z <= upper:
            return {
                "metric": "freshness",
                "tone": tone,
                "headline": headline,
                "detail": None,
                "band": band,
            }
    return {
        "metric": "freshness",
        "tone": "good",
        "headline": "You're notably fresh — a good day to push if you want to.",
        "detail": None,
        "band": "very_fresh",
    }


def consistency_insight(monotony_strain: dict[str, Any] | None) -> dict[str, Any]:
    """Plain-language reframing of monotony (metrics/load.py: compute_
    monotony_strain()) — never shown as a raw ratio. "Strain" (the other
    half of that function's output) doesn't get its own insight at all:
    unlike monotony, it has no natural self-relative reading built yet
    (would need a historical distribution the way TSB's z-score has), so
    surfacing it as a plain sentence here would mean inventing a threshold
    with even less backing than the ones already documented in this
    module — left out rather than guessed at.
    """
    if monotony_strain is None or monotony_strain.get("confidence") == "insufficient_data":
        return {
            "metric": "consistency",
            "tone": "unknown",
            "headline": "Not enough of this week logged yet to say.",
            "detail": None,
        }
    if monotony_strain.get("confidence") == "undefined_zero_variance":
        return {
            "metric": "consistency",
            "tone": "neutral",
            "headline": "You've trained the exact same amount every day this week.",
            "detail": None,
        }
    if monotony_strain.get("flag_high_monotony"):
        return {
            "metric": "consistency",
            "tone": "neutral",
            "headline": "This week's training has been similar intensity every day.",
            "detail": (
                "Mixing in a genuinely easy day (or a harder one) can help both fitness "
                "and recovery."
            ),
        }
    return {
        "metric": "consistency",
        "tone": "good",
        "headline": "This week has had a healthy mix of harder and easier days.",
        "detail": None,
    }


def correlation_insight(result: dict[str, Any]) -> dict[str, Any] | None:
    """One correlation result -> a plain sentence, or `None` if it isn't a
    real, confirmed pattern (design principle 6 applies here too — silence
    is the correct output for "not enough data" or "not significant," never
    a guessed insight). The underlying rigor (n>=30, Bonferroni correction)
    is unchanged and still real — just not shown as rho/p-value text to a
    reader who asked for no jargon; `n` (a plain "backed by N real days")
    is the one number kept visible, everything else stays in
    `metrics/correlations.py` for anyone who wants to check the math.
    """
    if result.get("confidence") != "significant" or result.get("rho") is None:
        return None

    x_name, y_name = result.get("x_name"), result.get("y_name")
    key = (x_name, y_name)
    plain = _PLAIN_PAIR_TEXT.get(key, result.get("description") or "a real pattern")
    plain_rho = _plain_language_rho(result["rho"], x_name, y_name)
    direction = (
        "the more one goes up, the more the other does too"
        if plain_rho > 0
        else "when one goes up, the other tends to go down"
    )
    return {
        "headline": f"Real pattern found: {plain} — {direction}.",
        "detail": f"Backed by {result.get('n')} real days of data, not a coincidence.",
    }
