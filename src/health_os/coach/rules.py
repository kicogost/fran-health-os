"""Deterministic coaching rules engine (kickoff doc section 7, Phase 7).

"Deterministic rules first, prose second" (kickoff doc's own framing): this
module produces a decision + reasons; `coach/briefing.py` only narrates what
comes out of here — it never invents a recommendation the rules didn't
produce. Pure functions taking already-computed inputs from `metrics/*.py`
and `config/athlete.yaml`, same layering `metrics/readiness.py` itself uses
(it deliberately takes component values, not raw histories) — this module is
one layer up: assembling coaching *decisions* from those already-computed
metrics, never recomputing them itself.

Two hard safety rails are enforced BY CONSTRUCTION rather than by a runtime
check, and that's documented explicitly rather than left implicit:
- **Never recommend running.** `_SESSION_GUIDANCE`'s vocabulary of session
  types (drawn from `config/athlete.yaml: comp_prep.weekly_template`) never
  includes running in the first place — there is no code path that could
  emit it, because the athlete's own weekly architecture never schedules it
  (the prior knee injury guardrail lives at the config layer already).
- **Never add a 4th/5th hard session.** `session_guidance()` only ever
  narrates sessions already present in `weekly_template` for the day; it has
  no mechanism to add one that isn't already scheduled.

Was previously a "simplified preview" embedded directly in
`dashboard/views/today.py` (2026-08-28) — moved here as the canonical
version once Phase 7 existed to own it (ADR 0005 is part of why: the future
frontend should be built against this real module, not a dashboard-local
copy).
"""

from __future__ import annotations

from typing import Any

from health_os.metrics import baselines
from health_os.metrics import load as load_metrics

READINESS_GREEN_THRESHOLD = 75.0
READINESS_AMBER_THRESHOLD = 55.0

STRUCTURAL_TSB_NEGATIVE_DAYS = 4
STRUCTURAL_MONOTONY_LOOKBACK_WEEKS = 8


def classify_readiness_band(score: float | None) -> str:
    """Kickoff doc section 7's readiness bands. Canonical source — anything
    that needs a band (dashboard, briefing) imports this rather than keeping
    its own copy of the 75/55 thresholds.
    """
    if score is None:
        return "no_data"
    if score >= READINESS_GREEN_THRESHOLD:
        return "green"
    if score >= READINESS_AMBER_THRESHOLD:
        return "amber"
    return "red"


def scheduled_sessions_for(config: dict[str, Any], weekday_name: str) -> list[dict[str, Any]]:
    """Sessions scheduled for `weekday_name` (lowercase, e.g. "friday") per
    `config/athlete.yaml: comp_prep.weekly_template`. Parameterized on the
    weekday name rather than reading the clock itself, so this is testable
    without mocking `datetime.now()`.
    """
    for day_entry in config["comp_prep"]["weekly_template"]:
        if day_entry["day"] == weekday_name:
            return day_entry["sessions"]
    return []


# (session_type, subtype) -> band -> instruction. `None` subtype is the
# fallback for a type with no subtype-specific entry (currently just "rest").
_SESSION_GUIDANCE: dict[tuple[str, str | None], dict[str, str]] = {
    ("bjj", "no_gi_technical"): {
        "green": "Live rounds in the rolling portion are fine.",
        "amber": "Keep the rolling portion technical/no-ego — drilling stays full effort.",
        "red": "Drilling only — skip the live rolling portion entirely.",
    },
    ("bjj", "hard_rounds"): {
        "green": "Full send — the week's highest-intensity day, and you're green-lit for it.",
        "amber": "Show up, but self-select intensity — push 2-3 rounds, ease off the rest.",
        "red": "Downgrade to drilling/positional work only — the wrong day to push through red.",
    },
    ("bjj", "open_mat"): {
        "green": "Go hard — full rounds at competition-style pace is fine.",
        "amber": "Cap it — aim for roughly 2/3 of your usual rounds, technical focus on the rest.",
        "red": "Drilling only if you go at all — skip live rolling entirely.",
    },
    ("bike", "easy_z2"): {
        "green": "Upper end of your range is fine, Z3 included if legs feel good.",
        "amber": "Strictly Z2, stay toward the lower end of your usual range.",
        "red": "Z2 only, and consider cutting the ride short.",
    },
    ("calisthenics", "strength_a"): {
        "green": "Attempt a load progression.",
        "amber": "Hold current load, don't push a new PR.",
        "red": "Mobility + light kettlebell instead of the full session.",
    },
    ("calisthenics", "strength_b"): {
        "green": "Attempt a load progression.",
        "amber": "Hold current load, don't push a new PR.",
        "red": "Mobility + light kettlebell instead of the full session.",
    },
    ("rest", None): {
        "green": "Full rest as scheduled.",
        "amber": "Rest day — good timing.",
        "red": "Rest day — good timing, lean into it.",
    },
}

_NECK_NIGGLE_OVERRIDE = (
    "Hold current load — a neck niggle was logged in the last 7 days, so pressing/"
    "overhead progression is paused regardless of readiness (hard injury guardrail, "
    "config/athlete.yaml: injuries.conditional)."
)


def has_recent_neck_niggle(niggles_texts: list[str | None]) -> bool:
    """True if any niggles free-text (from `subjective_log` or `bjj_sessions`
    in the trailing 7 days — caller supplies the already-windowed texts)
    mentions the neck. Case-insensitive substring match — a blunt instrument,
    but the guardrail is meant to err toward pausing progression too often
    rather than missing a real one.
    """
    return any("neck" in (t or "").lower() for t in niggles_texts)


def session_guidance(
    session: dict[str, Any], band: str, *, recent_neck_niggle: bool = False
) -> str:
    """One instruction for one scheduled session, given today's readiness
    band. The neck-niggle injury guardrail overrides calisthenics guidance
    regardless of band — a hard rail, not a readiness-dependent one (kickoff
    doc section 7: "never increase load on pressing/overhead work in any
    week where a neck niggle was logged").
    """
    session_type, subtype = session["type"], session.get("subtype")
    if recent_neck_niggle and session_type == "calisthenics":
        return _NECK_NIGGLE_OVERRIDE
    if band == "no_data":
        return "No readiness score yet to calibrate intensity — go by feel."
    table = _SESSION_GUIDANCE.get((session_type, subtype)) or _SESSION_GUIDANCE.get(
        (session_type, None)
    )
    if not table:
        return "No guidance rule written for this session type yet."
    return table[band]


def should_downgrade_to_rest(recent_bands: list[str]) -> bool:
    """True once the readiness signal has been persistently bad enough to
    justify downgrading a scheduled session toward rest — kickoff doc
    section 7: "never prescribe a full rest day off one bad number... require
    2 consecutive red days or 3 amber days first." `recent_bands` is the
    trailing sequence of band labels ("green"/"amber"/"red"/"no_data"),
    most-recent last — caller computes this from real readiness-score
    history (see `coach/briefing.py`).
    """
    if recent_bands[-2:] == ["red", "red"]:
        return True
    return recent_bands[-3:].count("amber") == 3


def hrv_sustained_low(hrv_observations: list[tuple[str, float]], *, window_days: int = 3) -> bool:
    """True if each of the last `window_days` days' HRV sat >1 SD below its
    OWN trailing 60-day baseline as of that day (kickoff doc section 7's
    structural trigger) — recomputes `compute_hrv_baseline()` for each of the
    last few days by truncating the observation list, the same
    "baseline that slides day to day" approach `compute_rhr_baseline()`
    already uses internally for `sustained_rise_flag`.
    """
    if len(hrv_observations) < window_days:
        return False
    for i in range(len(hrv_observations) - window_days, len(hrv_observations)):
        as_of = hrv_observations[: i + 1]
        result = baselines.compute_hrv_baseline(as_of)
        if result["confidence"] != "full" or result["status"] != "low":
            return False
    return True


def tsb_persistently_negative(
    tsb_series: list[tuple[str, float]], *, window_days: int = STRUCTURAL_TSB_NEGATIVE_DAYS
) -> bool:
    """True if the last `window_days` days of TSB (from `compute_ctl_atl()`'s
    output) are all negative — deep accumulated fatigue without recovery.
    Kickoff doc section 7 flags the exact numeric threshold as "TBD once real
    load-unit calibration exists" — "negative" (any freshness deficit at all)
    is the documented placeholder condition here, not a made-up magnitude.
    """
    if len(tsb_series) < window_days:
        return False
    return all(tsb < 0 for _, tsb in tsb_series[-window_days:])


def monotony_strain_flag(
    daily_load_series: list[tuple[str, float]],
    *,
    lookback_weeks: int = STRUCTURAL_MONOTONY_LOOKBACK_WEEKS,
) -> bool:
    """True if the current trailing week's monotony is flagged (>2.0, Foster)
    AND this week's strain sits in the top quartile of the last
    `lookback_weeks` weeks' strain values — kickoff doc section 7's third
    structural trigger. Slides a 7-day window one day at a time (matching
    `compute_monotony_strain()`'s own trailing-window convention) rather than
    calendar-aligned weeks, so this is "the current week" as of the series'
    last date, not necessarily Mon-Sun.
    """
    if len(daily_load_series) < 7:
        return False
    weekly_results = [
        load_metrics.compute_monotony_strain(daily_load_series[end - 7 : end])
        for end in range(7, len(daily_load_series) + 1)
    ]
    current = weekly_results[-1]
    if current["confidence"] != "full" or not current["flag_high_monotony"]:
        return False
    # weekly_results has one entry PER DAY (a daily-sliding 7-day window, not
    # one entry per calendar week) -- so "last lookback_weeks weeks" means the
    # last (lookback_weeks * 7) of these overlapping daily windows, not the
    # last lookback_weeks entries of this list.
    recent = [r for r in weekly_results[-lookback_weeks * 7 :] if r["confidence"] == "full"]
    if len(recent) < 4:
        return False
    strains = sorted(r["strain"] for r in recent)
    top_quartile_cutoff = strains[int(len(strains) * 0.75)]
    return current["strain"] >= top_quartile_cutoff


def nutrition_focus(config: dict[str, Any], *, yesterday_social_meal: bool | None = None) -> str:
    """One nutrition reminder for the daily briefing (kickoff doc: "one
    nutrition focus"). The hard rails (never fasting, never a deficit deeper
    than `deficit_kcal_max` implies, never "making up" for a social meal) are
    enforced BY CONSTRUCTION here: this function's only possible outputs are
    two fixed, pre-approved sentences, neither of which can violate those
    rails — not generated text that would need separate checking.
    """
    protein_g = config["nutrition"]["protein_g_daily_min"]
    if yesterday_social_meal:
        return (
            f"Yesterday was a social meal — no compensating with extra training or a "
            f"skipped meal today. Just hit today's {protein_g}g protein target and move on."
        )
    return f"Hit {protein_g}g protein today — the one hard number that matters most."
