"""Assembles the Trends page's payload — weight/HRV/RHR/sleep-stage series
over a selectable trailing window, plus plain-language insights. Mirrors
`dashboard/views/trends.py` for the charts.

**Insights added 2026-08-30** (Francisco: "you need to tell me things you
see in trends from the data... no fluff no acronyms"): `insights` is a
short list of plain-English takeaways — "you're sleeping great," "you're
losing weight," etc. — built by `metrics/insights.py` from the SAME
baseline/trend computations that already power other pages (HRV/RHR
baselines, the weight OLS trend, the correlation engine), not a new,
separately-computed set of numbers. Always includes weight/sleep/HRV/RHR
(even as an honest "not enough data yet" when that's the real state) plus
zero or more correlation findings, only when a real, statistically
confirmed one exists.

**Per-chart window average + meaning added 2026-09-09** (Francisco: a live
average for whatever window is on screen, next to every chart, plus a
plain sentence on what that average means). Every series below now carries
`average` (`{"value", "n_days"}`) and `meaning` (`{"tone", "headline"}`)
alongside its existing `raw`/`smoothed` arrays. Two hard rules, both load-
bearing for why this feature is trustworthy rather than a second, silently
driftable copy of numbers already shown elsewhere on this page:

1. **The average is always `_window_average()` of the exact list already
   returned as that series' own `raw` array** — never a separately-fetched
   or separately-windowed query. `TestWindowAverageMatchesRaw` in the test
   suite locks this in for every metric so it can't quietly drift later.
2. **The "what it means" sentence is never a new, ad hoc heuristic** — it
   reuses the SAME already-computed classification objects the top-of-page
   insight cards use (`body_comp.weight_trend_ols()`'s OLS trend + comp
   countdown, `baselines.compute_hrv_baseline()`/`compute_rhr_baseline()`),
   computed ONCE per request and passed into both `_build_insights()` and
   the new per-series meaning builders below — not recomputed a second time
   per call site (this project's own repeated "two independent copies of
   the same thing drift apart" lesson, see CLAUDE.md). The one genuinely
   NEW piece of analysis is the readiness "weakest component" read, built
   from `derived_daily.inputs_json`'s already-persisted component
   breakdown (design principle 9) — never a guessed reason.

**Body fat % / fat mass added 2026-09-11** (Francisco, once the Renpho CSV
body-composition backfill landed real `body_fat_pct` data: "is my weight
loss/gain coming from fat or muscle" — see CLAUDE.md's Renpho CSV section).
Two new `series` entries, built with the exact same per-chart-average/
meaning discipline as every series above, not a new heuristic:

- **`body_fat_pct`** — a real `daily_metrics` column, so it flows through
  the SAME generic `_TIME_SERIES_COLUMNS` loop weight/HRV/RHR already use
  (one query, one `average`, one `meaning`). Its trend comes from
  `body_comp.body_fat_pct_trend_ols()` (a thin sibling of
  `weight_trend_ols()` for a %-point unit instead of kg — see that
  function's own docstring for why it isn't just a direct call to
  `weight_trend_ols()`).
- **`fat_mass_kg`** — NOT a stored column: `body_comp.compute_fat_mass_series()`
  joins `weight_kg` and `body_fat_pct` per date (only where BOTH are real
  that day, design principle 6), and the result is fed straight into
  `compute_weight_ewma()`/`weight_trend_ols()` UNCHANGED — fat mass is
  genuinely measured in kg, so weight's own kg-labeled trend function is
  correct here, not just reused for convenience. Built by
  `_build_fat_mass_series()` below, mirroring `_build_sleep_total()`'s shape
  for a derived (non-column) series, except this one DOES carry a
  `smoothed` line (a real EWMA/OLS-trend-tracked series in its own right,
  not a caption-only number).

Deliberately does NOT compare either series against a target body-fat %
(unlike weight's own comparison against `goals.primary.weight_division_kg`)
— a real, evidence-based target number is being researched separately and
doesn't exist yet. See `_body_fat_pct_window_meaning()`'s docstring for
exactly where that comparison would slot in once one is decided.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Any

from health_os.coach import rules
from health_os.metrics import baselines, body_comp, insights
from health_os.metrics.correlations import build_daily_metrics_correlation_panel

ALLOWED_WINDOW_DAYS = (30, 90, 365)
DEFAULT_SMOOTH_SPAN_DAYS = 7

_TIME_SERIES_COLUMNS = {
    "weight_kg": "Weight",
    "hrv_overnight_ms": "HRV (overnight)",
    "resting_hr": "Resting heart rate",
    "body_fat_pct": "Body fat %",
}
_READINESS_METRIC_NAME = "readiness_score"
_SLEEP_STAGE_COLUMNS = {
    "sleep_deep_min": "Deep",
    "sleep_light_min": "Light",
    "sleep_rem_min": "REM",
    "sleep_awake_min": "Awake",
}

# Plain-English phrase for whichever readiness component has scored weakest
# on average across the window — keyed the same way
# `metrics/readiness.py: compute_readiness_score()`'s own `components` dict
# is. HRV and RHR share one phrase (both are "recovery" signals from the
# athlete's own perspective; the underlying `_readiness_weakest_component()`
# still picks between them individually, this is just how each reads once
# picked).
_READINESS_WEAK_COMPONENT_PHRASES: dict[str, str] = {
    "hrv": "gave your body more recovery time",
    "rhr": "gave your body more recovery time",
    "sleep": "slept more consistently",
    "subjective": "kept logging how you feel — it's missing some days",
}

# A reasoned, documented default (no literature threshold exists for "how
# many real days of component detail before naming a weakest one is
# trustworthy") — same spirit as this project's other seed-phase constants
# (e.g. `body_comp.MIN_POINTS_FOR_TREND`). Below this, say so honestly
# rather than naming a "weakest" component off a handful of points that
# could easily be noise (design principle 6).
READINESS_MIN_DAYS_FOR_WEAK_COMPONENT = 5


def _smooth(observations: list[tuple[str, float]], span_days: int = DEFAULT_SMOOTH_SPAN_DAYS):
    """Same recursive-EWMA math as `dashboard/data.py: smooth_for_display()`
    -- kept as its own small copy here rather than importing from
    `dashboard/` (which pulls in Streamlit at module level), for the exact
    "no analytical claims of its own, purely for chart smoothing" reasoning
    that function's own docstring already gives.
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


def _window_average(values: list[float]) -> float | None:
    """Plain mean of `values` -- the one function every "average for this
    window" figure on this page goes through. Always called with the SAME
    list already used to build a chart's own `raw` array (never a second,
    independently-windowed query), so the displayed average can't silently
    drift from what's plotted (constraint enforced by
    `TestWindowAverageMatchesRaw` in the test suite).
    """
    return sum(values) / len(values) if values else None


def _trailing_week_avg(
    observations: list[tuple[str, float]], as_of: str, weeks_back: int
) -> float | None:
    """Plain average of `observations` over the 7-day window ending
    `weeks_back` weeks before `as_of` (0 = the week ending on `as_of`
    itself). `None` if that window has no real readings at all.
    """
    end = date.fromisoformat(as_of) - timedelta(days=7 * weeks_back)
    start = end - timedelta(days=6)
    vals = [v for d, v in observations if start.isoformat() <= d <= end.isoformat()]
    return sum(vals) / len(vals) if vals else None


def _fetch_col_obs(conn: sqlite3.Connection, column: str) -> list[tuple[str, float]]:
    """Full available history (never windowed by the 30/90/365 selector) for
    one `daily_metrics` column — shared by every full-history computation
    below (the weight OLS trend, the HRV/RHR baselines, sleep debt) so
    there's exactly one query per column, not one per caller.
    """
    rows = conn.execute(
        f"SELECT date, {column} AS v FROM daily_metrics "  # noqa: S608
        f"WHERE {column} IS NOT NULL ORDER BY date",
    ).fetchall()
    return [(r["date"], r["v"]) for r in rows]


def _weight_window_meaning(
    avg: float | None,
    trend: dict[str, Any],
    weight_limit_kg: float | None,
    comp_countdown: dict[str, Any] | None,
) -> dict[str, Any]:
    """Weight's plain-language window read. `avg` is the WINDOWED chart
    average (constraint: computed from the same `raw` array as the chart);
    `trend` is the already-computed full-history 21-day OLS slope
    (`body_comp.weight_trend_ols()`, the exact object
    `insights.weight_insight()` uses for the top-of-page card) — reused
    here for direction/rate rather than re-derived from the two chart
    endpoints, which this project has learned the hard way is a real class
    of bug (two independent "trend" reads silently disagreeing).
    """
    if avg is None:
        return {"tone": "unknown", "headline": "No weight logged in this window yet."}

    kg_over_limit = (avg - weight_limit_kg) if weight_limit_kg is not None else None
    if kg_over_limit is None:
        limit_clause = ""
    elif kg_over_limit <= 0:
        limit_clause = " — already at or under your competition weight limit"
    else:
        limit_clause = f" — {kg_over_limit:.1f}kg above your competition weight limit"

    trend_known = trend.get("confidence") == "full" and trend.get("slope_kg_per_week") is not None
    if not trend_known:
        headline = (
            f"Averaging {avg:.1f}kg this window{limit_clause} — not enough recent weigh-ins "
            "to see a trend yet."
        )
        tone = "unknown" if kg_over_limit is None else "bad" if kg_over_limit > 0 else "good"
        return {"tone": tone, "headline": headline}

    slope = trend["slope_kg_per_week"]
    ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
    distinguishable = not (ci_low <= 0 <= ci_high)

    if not distinguishable:
        headline = f"Averaging {avg:.1f}kg this window{limit_clause} — holding steady."
        tone = "neutral" if kg_over_limit is None else "bad" if kg_over_limit > 0 else "good"
        return {"tone": tone, "headline": headline}

    if slope < 0:
        headline = (
            f"Averaging {avg:.1f}kg this window{limit_clause} — you've been losing, "
            f"about {abs(slope):.1f}kg/week."
        )
        if comp_countdown is not None and comp_countdown.get("red_flag"):
            headline += " At this pace you won't make weight in time."
            tone = "neutral"
        else:
            tone = "good"
        return {"tone": tone, "headline": headline}

    headline = (
        f"Averaging {avg:.1f}kg this window{limit_clause} — you've been gaining, "
        f"about {slope:.1f}kg/week."
    )
    return {"tone": "bad", "headline": headline}


def _hrv_window_meaning(avg: float | None, baseline: dict[str, Any]) -> dict[str, Any]:
    """Reuses `baselines.classify_deviation()` -- the exact +-1 SD rule
    `compute_hrv_baseline()` applies to its own latest observation -- to
    classify the WINDOWED AVERAGE against Francisco's own real 60-day
    baseline (`baseline["baseline_median"]`/`["baseline_sd"]`, already
    computed once for the top-of-page insight card, not recomputed here).
    "recovery signal," not the bare acronym "HRV," matching
    `insights.hrv_insight()`'s own established phrasing.
    """
    if avg is None:
        return {"tone": "unknown", "headline": "No recovery-signal readings in this window yet."}
    if baseline.get("confidence") != "full":
        return {
            "tone": "unknown",
            "headline": (
                f"Averaging {avg:.0f}ms this window — not enough recovery-signal history yet "
                "to say what's normal for you."
            ),
        }
    _, status = baselines.classify_deviation(
        avg, baseline["baseline_median"], baseline["baseline_sd"]
    )
    if status == "high":
        tone, phrase = "good", "above your normal range — a good recovery sign"
    elif status == "low":
        tone, phrase = "bad", "below your normal range — you may need more recovery"
    else:
        tone, phrase = "neutral", "right around your normal range"
    return {"tone": tone, "headline": f"Averaging {avg:.0f}ms this window — {phrase}."}


def _rhr_window_meaning(avg: float | None, baseline: dict[str, Any]) -> dict[str, Any]:
    """Same shared classifier as `_hrv_window_meaning()`, direction inverted
    (a LOWER resting heart rate than your own normal is the good sign) —
    matching `insights.rhr_insight()`'s established polarity.
    """
    if avg is None:
        return {"tone": "unknown", "headline": "No resting-heart-rate readings in this window yet."}
    if baseline.get("confidence") != "full":
        return {
            "tone": "unknown",
            "headline": (
                f"Averaging {avg:.0f}bpm this window — not enough resting-heart-rate history "
                "yet to say what's normal for you."
            ),
        }
    _, status = baselines.classify_deviation(
        avg, baseline["baseline_median"], baseline["baseline_sd"]
    )
    if status == "high":
        tone, phrase = "bad", "a bit elevated versus your normal range"
    elif status == "low":
        tone, phrase = "good", "lower than your normal range — a good sign"
    else:
        tone, phrase = "neutral", "right around your normal range"
    return {"tone": tone, "headline": f"Averaging {avg:.0f}bpm this window — {phrase}."}


def _body_fat_pct_window_meaning(avg: float | None, trend: dict[str, Any]) -> dict[str, Any]:
    """`trend` is the FULL-HISTORY `body_comp.body_fat_pct_trend_ols()` 21-day
    OLS slope (computed once by the caller, same "compute once, reuse"
    discipline as weight/HRV/RHR above) -- `avg` is the WINDOWED chart
    average (constraint: `_window_average()` of the same `raw` array the
    chart itself renders).

    Deliberately has NO clause comparing `avg` against a target body-fat %
    the way `_weight_window_meaning()` compares against
    `goals.primary.weight_division_kg` -- no such target number has been
    decided yet (a real, evidence-based one is being researched separately,
    per CLAUDE.md). Once one exists, a comparison clause can slot in here
    the same way weight's `limit_clause`/`comp_countdown` detail works
    today -- left out for now on purpose, not an oversight.
    """
    if avg is None:
        return {"tone": "unknown", "headline": "No body-fat readings in this window yet."}

    trend_known = trend.get("confidence") == "full" and trend.get("slope_pct_per_week") is not None
    if not trend_known:
        return {
            "tone": "unknown",
            "headline": (
                f"Averaging {avg:.1f}% body fat this window — not enough recent readings "
                "to see a trend yet."
            ),
        }

    slope = trend["slope_pct_per_week"]
    ci_low, ci_high = trend["ci_low_pct_per_week"], trend["ci_high_pct_per_week"]
    distinguishable = not (ci_low <= 0 <= ci_high)

    if not distinguishable:
        return {
            "tone": "neutral",
            "headline": f"Averaging {avg:.1f}% body fat this window — holding steady.",
        }
    if slope < 0:
        return {
            "tone": "good",
            "headline": (
                f"Averaging {avg:.1f}% body fat this window — trending down, about "
                f"{abs(slope):.1f} points a week."
            ),
        }
    return {
        "tone": "bad",
        "headline": (
            f"Averaging {avg:.1f}% body fat this window — trending up, about "
            f"{slope:.1f} points a week."
        ),
    }


def _fat_mass_window_meaning(avg: float | None, trend: dict[str, Any]) -> dict[str, Any]:
    """`trend` is the FULL-HISTORY `body_comp.weight_trend_ols()` result
    applied to the fat-mass-kg series (`compute_fat_mass_series()`) --
    reused unchanged since fat mass really is in kg, same as weight. `avg`
    is the windowed chart average of that same joined series.

    This is the number that actually answers "is my weight change coming
    from fat or muscle": a real, computed kg trend, not an inference — fat
    mass is literally weight_kg * body_fat_pct / 100, so a falling fat-mass
    trend means falling fat, by definition of the inputs, not a guess.
    """
    if avg is None:
        return {
            "tone": "unknown",
            "headline": (
                "Not enough days with both a weigh-in and a body-fat reading in this "
                "window yet to work out fat mass."
            ),
        }

    trend_known = trend.get("confidence") == "full" and trend.get("slope_kg_per_week") is not None
    if not trend_known:
        return {
            "tone": "unknown",
            "headline": (
                f"Averaging {avg:.1f}kg of fat mass this window — not enough recent "
                "readings to see a trend yet."
            ),
        }

    slope = trend["slope_kg_per_week"]
    ci_low, ci_high = trend["ci_low_kg_per_week"], trend["ci_high_kg_per_week"]
    distinguishable = not (ci_low <= 0 <= ci_high)

    if not distinguishable:
        return {
            "tone": "neutral",
            "headline": f"Averaging {avg:.1f}kg of fat mass this window — holding steady.",
        }
    if slope < 0:
        return {
            "tone": "good",
            "headline": (
                f"Averaging {avg:.1f}kg of fat mass this window — trending down, about "
                f"{abs(slope):.1f}kg/week. That's real fat loss, not just water or muscle."
            ),
        }
    return {
        "tone": "bad",
        "headline": (
            f"Averaging {avg:.1f}kg of fat mass this window — trending up, about "
            f"{slope:.1f}kg/week."
        ),
    }


def _sleep_total_window_meaning(avg_minutes: float | None) -> dict[str, Any]:
    """Average total sleep duration (deep+light+rem, awake time excluded —
    see `_build_sleep_total()`) vs. the same 7-9h band ADR 0007 established
    for the readiness score's own sleep component
    (`baselines.DEFAULT_NIGHTLY_NEED_HOURS`/`DEFAULT_NIGHTLY_NEED_UPPER_HOURS`).
    """
    if avg_minutes is None:
        return {"tone": "unknown", "headline": "No sleep data in this window yet."}
    avg_hours = avg_minutes / 60.0
    formatted = insights.format_hours_minutes(avg_hours)
    if avg_hours < baselines.DEFAULT_NIGHTLY_NEED_HOURS:
        return {
            "tone": "bad",
            "headline": (
                f"Averaging {formatted} a night this window — under the 7-9 hour range "
                "you're aiming for."
            ),
        }
    if avg_hours > baselines.DEFAULT_NIGHTLY_NEED_UPPER_HOURS:
        return {
            "tone": "neutral",
            "headline": (
                f"Averaging {formatted} a night this window — above the usual 7-9 hour range."
            ),
        }
    return {
        "tone": "good",
        "headline": (
            f"Averaging {formatted} a night this window — right in the 7-9 hour range "
            "you're aiming for."
        ),
    }


def _readiness_weakest_component(rows: list[sqlite3.Row]) -> str | None:
    """Whichever of hrv/rhr/sleep/subjective has had the lowest AVERAGE
    0-100 sub-score across the window, read from `derived_daily.inputs_json`'s
    already-persisted component breakdown (`metrics/readiness.py:
    compute_readiness_score()`'s own `components` dict, stored verbatim by
    `metrics/derived_daily.py`) — the exact numbers `readiness_score` itself
    was built from that day, never a second, independently-recomputed
    classification. `None` if no component has enough real days in the
    window to trust naming one as "weakest."
    """
    scores: dict[str, list[float]] = {}
    for r in rows:
        raw_inputs = r["inputs_json"]
        if not raw_inputs:
            continue
        inputs = json.loads(raw_inputs)
        for name, comp in (inputs.get("components") or {}).items():
            if name in _READINESS_WEAK_COMPONENT_PHRASES and comp.get("score") is not None:
                scores.setdefault(name, []).append(comp["score"])
    candidates = {
        name: sum(vals) / len(vals)
        for name, vals in scores.items()
        if len(vals) >= READINESS_MIN_DAYS_FOR_WEAK_COMPONENT
    }
    if not candidates:
        return None
    return min(candidates, key=candidates.get)


def _readiness_window_meaning(rows: list[sqlite3.Row], avg: float | None) -> dict[str, Any]:
    """`avg` is the mean of the exact same `value`s returned in
    `readiness["raw"]`. Band classification goes through
    `coach.rules.classify_readiness_band()` — the one canonical 75/55
    threshold source, never a second hardcoded copy. The "could be better
    if..." clause is the one genuinely new analysis this feature adds — see
    `_readiness_weakest_component()`.
    """
    if avg is None:
        return {"tone": "unknown", "headline": "Not enough readiness history in this window yet."}

    band = rules.classify_readiness_band(avg)
    weakest = _readiness_weakest_component(rows)

    if band == "green":
        return {
            "tone": "good",
            "headline": (
                f"Averaging {avg:.0f} this window — you've consistently been ready to push."
            ),
        }

    detail = (
        f" It would help most if you {_READINESS_WEAK_COMPONENT_PHRASES[weakest]}."
        if weakest is not None
        else " Not enough day-by-day detail yet to say what would help most."
    )
    if band == "amber":
        return {
            "tone": "neutral",
            "headline": f"Averaging {avg:.0f} this window — okay, but could be better.{detail}",
        }
    return {
        "tone": "bad",
        "headline": f"Averaging {avg:.0f} this window — running low.{detail}",
    }


def _build_insights(
    conn: sqlite3.Connection,
    *,
    weight_obs: list[tuple[str, float]],
    trend: dict[str, Any],
    comp_countdown: dict[str, Any] | None,
    sleep_obs: list[tuple[str, float]],
    sleep_debt: dict[str, Any],
    hrv_baseline: dict[str, Any],
    rhr_baseline: dict[str, Any],
) -> list[dict[str, Any]]:
    """Uses the FULL available history for every input (never windowed by
    the 30/90/365 selector) — same reasoning `correlations.py` already uses:
    more real history only helps these, never hurts. `trend`/`comp_countdown`/
    `sleep_debt`/`hrv_baseline`/`rhr_baseline` are all computed ONCE by the
    caller (`build_trends_payload()`) and passed in here rather than
    recomputed — the same objects also feed the new per-chart window-average
    "meaning" text (2026-09-09), so there is exactly one computation of each,
    not two independently-driftable ones.
    """
    result: list[dict[str, Any]] = []

    result.append(insights.weight_insight(trend, comp_countdown))

    this_week_avg = last_week_avg = None
    if sleep_obs:
        as_of = sleep_obs[-1][0]
        this_week_avg = _trailing_week_avg(sleep_obs, as_of, 0)
        last_week_avg = _trailing_week_avg(sleep_obs, as_of, 1)
        if this_week_avg is not None:
            this_week_avg /= 60.0
        if last_week_avg is not None:
            last_week_avg /= 60.0
    result.append(insights.sleep_insight(sleep_debt, this_week_avg, last_week_avg))

    result.append(insights.hrv_insight(hrv_baseline))
    result.append(insights.rhr_insight(rhr_baseline))

    correlations = build_daily_metrics_correlation_panel(conn)
    for r in correlations:
        corr_insight = insights.correlation_insight(
            {
                "confidence": r.confidence,
                "rho": r.rho,
                "n": r.n,
                "x_name": r.x_name,
                "y_name": r.y_name,
                "description": r.description,
            }
        )
        if corr_insight is not None:
            result.append({"metric": "correlation", "tone": "info", **corr_insight})

    return result


def _build_sleep_total(stage_rows: list[sqlite3.Row]) -> dict[str, Any]:
    """Total sleep duration per day = deep + light + rem minutes, summed
    from the SAME `stage_rows` already used to build the "Sleep stages"
    stacked-bar chart's data — constraint #1 (no separately-fetched
    computation). Awake minutes are deliberately excluded from this sum:
    time spent awake during the night isn't sleep, so including it would
    overstate "how much you actually slept." A day only contributes to this
    average when all three of deep/light/rem are present for it — a
    partial stage breakdown is never summed as if it were the whole night
    (design principle 6).
    """
    raw: list[dict[str, Any]] = []
    for r in stage_rows:
        deep, light, rem = r["sleep_deep_min"], r["sleep_light_min"], r["sleep_rem_min"]
        if deep is not None and light is not None and rem is not None:
            raw.append({"date": r["date"], "value": deep + light + rem})

    values = [p["value"] for p in raw]
    avg = _window_average(values)
    return {
        "label": "Total sleep",
        "raw": raw,
        "average": {"value": avg, "n_days": len(values)},
        "meaning": _sleep_total_window_meaning(avg),
    }


def _build_fat_mass_series(
    cutoff: str,
    weight_obs_full: list[tuple[str, float]],
    body_fat_pct_obs_full: list[tuple[str, float]],
    fat_mass_trend: dict[str, Any],
) -> dict[str, Any]:
    """Fat mass (kg) isn't a stored `daily_metrics` column, so it can't flow
    through the generic `_TIME_SERIES_COLUMNS` loop the way `body_fat_pct`
    does -- built here instead, mirroring that loop's own shape exactly
    (`label`/`raw`/`smoothed`/`average`/`meaning`) so the payload entry is a
    real `TimeSeries`, not a second, thinner shape.

    `weight_obs_full`/`body_fat_pct_obs_full` are the SAME full-history
    lists the caller already fetched for the weight/body-fat trend
    computations -- joined ONCE via `body_comp.compute_fat_mass_series()`
    then filtered to the display window, never a second, independently-
    windowed query (the same "average always matches what's plotted"
    constraint every other series in this module upholds).
    """
    fat_mass_obs_full = body_comp.compute_fat_mass_series(weight_obs_full, body_fat_pct_obs_full)
    windowed = [(d, v) for d, v in fat_mass_obs_full if d >= cutoff]
    values = [v for _, v in windowed]
    avg = _window_average(values)
    return {
        "label": "Fat mass",
        "raw": [{"date": d, "value": v} for d, v in windowed],
        "smoothed": [{"date": d, "value": v} for d, v in _smooth(windowed)],
        "average": {"value": avg, "n_days": len(values)},
        "meaning": _fat_mass_window_meaning(avg, fat_mass_trend),
    }


def build_trends_payload(
    conn: sqlite3.Connection, window_days: int, config: dict[str, Any]
) -> dict[str, Any]:
    """Everything the Trends page needs for one window, as one JSON-ready
    dict. `window_days` should be one of `ALLOWED_WINDOW_DAYS` -- the caller
    (the FastAPI route) validates that, this function just uses whatever
    it's given. `insights` is unaffected by `window_days` (see
    `_build_insights()`'s own docstring); every series' `average`/`meaning`
    IS affected by it (that's the point — it updates whenever the window
    selector changes), even though the classification objects underneath
    (trend/baselines) are themselves full-history.
    """
    max_row = conn.execute("SELECT MAX(date) AS d FROM daily_metrics").fetchone()
    if max_row["d"] is None:
        empty_average = {"value": None, "n_days": 0}
        return {
            "window_days": window_days,
            "series": {},
            "sleep_stages": [],
            "sleep_total": {
                "label": "Total sleep",
                "raw": [],
                "average": dict(empty_average),
                "meaning": _sleep_total_window_meaning(None),
            },
            "readiness": {
                "label": "Readiness score",
                "raw": [],
                "smoothed": [],
                "coverage_summary": {},
                "average": dict(empty_average),
                "meaning": _readiness_window_meaning([], None),
            },
            "insights": [],
        }

    cutoff = (date.fromisoformat(max_row["d"]) - timedelta(days=window_days - 1)).isoformat()

    # Full-history inputs for the classification objects reused by both
    # `_build_insights()` (the top-of-page cards) and every per-chart
    # window-average "meaning" below — computed exactly once.
    weight_obs_full = _fetch_col_obs(conn, "weight_kg")
    hrv_obs_full = _fetch_col_obs(conn, "hrv_overnight_ms")
    rhr_obs_full = _fetch_col_obs(conn, "resting_hr")
    sleep_obs_full = _fetch_col_obs(conn, "sleep_total_min")
    body_fat_pct_obs_full = _fetch_col_obs(conn, "body_fat_pct")

    trend = body_comp.weight_trend_ols(weight_obs_full)
    body_fat_trend = body_comp.body_fat_pct_trend_ols(body_fat_pct_obs_full)
    fat_mass_obs_full = body_comp.compute_fat_mass_series(weight_obs_full, body_fat_pct_obs_full)
    fat_mass_trend = body_comp.weight_trend_ols(fat_mass_obs_full)
    goal = config.get("goals", {}).get("primary")
    weight_limit_kg = goal.get("weight_division_kg") if goal is not None else None
    comp_countdown = None
    if weight_obs_full and goal is not None:
        ewma_series = body_comp.compute_weight_ewma(weight_obs_full)
        comp_countdown = body_comp.comp_countdown(
            current_weight_kg=ewma_series[-1][1],
            trend_slope_kg_per_week=trend["slope_kg_per_week"],
            comp_date=goal["date"],
            weight_limit_kg=goal["weight_division_kg"],
            today=weight_obs_full[-1][0],
        )

    hrv_baseline = baselines.compute_hrv_baseline(hrv_obs_full)
    rhr_baseline = baselines.compute_rhr_baseline(rhr_obs_full)
    sleep_debt = baselines.compute_sleep_debt(sleep_obs_full)

    _MEANING_BUILDERS = {
        "weight_kg": (
            lambda avg: _weight_window_meaning(avg, trend, weight_limit_kg, comp_countdown)
        ),
        "hrv_overnight_ms": lambda avg: _hrv_window_meaning(avg, hrv_baseline),
        "resting_hr": lambda avg: _rhr_window_meaning(avg, rhr_baseline),
        "body_fat_pct": lambda avg: _body_fat_pct_window_meaning(avg, body_fat_trend),
    }

    series: dict[str, Any] = {}
    for column, label in _TIME_SERIES_COLUMNS.items():
        rows = conn.execute(
            f"SELECT date, {column} AS v FROM daily_metrics "  # noqa: S608
            f"WHERE {column} IS NOT NULL AND date >= ? ORDER BY date",
            (cutoff,),
        ).fetchall()
        obs = [(r["date"], r["v"]) for r in rows]
        values = [v for _, v in obs]
        avg = _window_average(values)
        series[column] = {
            "label": label,
            "raw": [{"date": d, "value": v} for d, v in obs],
            "smoothed": [{"date": d, "value": v} for d, v in _smooth(obs)],
            "average": {"value": avg, "n_days": len(values)},
            "meaning": _MEANING_BUILDERS[column](avg),
        }

    series["fat_mass_kg"] = _build_fat_mass_series(
        cutoff, weight_obs_full, body_fat_pct_obs_full, fat_mass_trend
    )

    stage_rows = conn.execute(
        "SELECT date, sleep_deep_min, sleep_light_min, sleep_rem_min, sleep_awake_min "
        "FROM daily_metrics WHERE date >= ? "
        "AND (sleep_deep_min IS NOT NULL OR sleep_light_min IS NOT NULL "
        "OR sleep_rem_min IS NOT NULL OR sleep_awake_min IS NOT NULL) "
        "ORDER BY date",
        (cutoff,),
    ).fetchall()
    sleep_stages = [
        {
            "date": r["date"],
            **{col: r[col] for col in _SLEEP_STAGE_COLUMNS if r[col] is not None},
        }
        for r in stage_rows
    ]
    sleep_total = _build_sleep_total(stage_rows)

    readiness = _build_readiness_history(conn, cutoff)

    return {
        "window_days": window_days,
        "series": series,
        "sleep_stages": sleep_stages,
        "sleep_total": sleep_total,
        "readiness": readiness,
        "insights": _build_insights(
            conn,
            weight_obs=weight_obs_full,
            trend=trend,
            comp_countdown=comp_countdown,
            sleep_obs=sleep_obs_full,
            sleep_debt=sleep_debt,
            hrv_baseline=hrv_baseline,
            rhr_baseline=rhr_baseline,
        ),
    }


def _build_readiness_history(conn: sqlite3.Connection, cutoff: str) -> dict[str, Any]:
    """Readiness score over time, straight from `derived_daily` — real
    historical tracking of the composite itself, not just its inputs, now
    that it's actually persisted per date (added 2026-08-28) rather than
    only ever computed live for "today." Built 2026-08-30 after Francisco
    asked for this directly.

    `derived_daily` is a long/tall table (one row per (date, metric_name)),
    unlike `daily_metrics`'s wide columns, hence its own small query rather
    than reusing `_TIME_SERIES_COLUMNS`'s loop.

    Confidence is never hidden or averaged away (design principle 6) — most
    days will read "partial" (only the subjective/Hooper component is
    typically missing) rather than invented as "full"; `coverage_summary`
    reports the real count of each confidence level actually present in
    this window so a reader isn't left guessing how much of the chart to
    trust.

    **2026-09-09**: also selects `inputs_json` now, so the window average's
    "meaning" text can identify the weakest real component
    (`_readiness_weakest_component()`) from the SAME rows already fetched
    for the chart — not a second query.
    """
    rows = conn.execute(
        "SELECT date, value, confidence, n_days, inputs_json FROM derived_daily "
        "WHERE metric_name = ? AND date >= ? AND value IS NOT NULL ORDER BY date",
        (_READINESS_METRIC_NAME, cutoff),
    ).fetchall()
    obs = [(r["date"], r["value"]) for r in rows]

    coverage_summary: dict[str, int] = {}
    for r in rows:
        key = r["confidence"] or "unknown"
        coverage_summary[key] = coverage_summary.get(key, 0) + 1

    values = [v for _, v in obs]
    avg = _window_average(values)

    return {
        "label": "Readiness score",
        "raw": [
            {"date": r["date"], "value": r["value"], "confidence": r["confidence"]} for r in rows
        ],
        "smoothed": [{"date": d, "value": v} for d, v in _smooth(obs)],
        "coverage_summary": coverage_summary,
        "average": {"value": avg, "n_days": len(values)},
        "meaning": _readiness_window_meaning(rows, avg),
    }
