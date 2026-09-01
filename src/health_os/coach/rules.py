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

from datetime import date, timedelta
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


def calisthenics_exercise_breakdown(config: dict[str, Any], subtype: str | None) -> str | None:
    """The real, prescribed exercise breakdown for a calisthenics session —
    `config/athlete.yaml: comp_prep.strength_sessions[subtype].exercises` —
    formatted into one readable line for Today's session card.

    **Real gap closed 2026-08-31**: `strength_sessions` already had a full,
    real per-exercise prescription (6 exercises with sets/reps/coaching
    notes per subtype) since the comp-prep plan was entered into config —
    confirmed by grep that neither this module, `coach/briefing.py`, nor
    `api/today.py` ever read it before this. Only `scripts/log_calisthenics.py`
    (the manual logger, `_load_prescribed_exercises()`) ever looked at it, so
    Today's session card showed a calisthenics day's type and duration only,
    never what the session actually consists of — contradicting Francisco's
    own stated goal for Today ("a breakdown for the exact workout I have on
    the day and how I should approach it").

    Returns `None` — never an invented placeholder — when `subtype` doesn't
    match a configured key (design principle 6: never invent data; e.g. a
    holiday-week substitution logged under a session type with no config
    entry, same gap already handled the same way by the manual logger).

    Joined with "; " into one line rather than one-per-line: each entry is
    already a short, self-contained "exercise: sets x reps (note)" string
    (verified against the real config — none contain a semicolon), and
    `SessionCard.tsx`'s `notes` slot renders a single paragraph, no
    multi-line support needed for a list this short.
    """
    strength_sessions = config.get("comp_prep", {}).get("strength_sessions", {})
    session_config = strength_sessions.get(subtype or "") if subtype else None
    if not session_config:
        return None
    exercises = session_config.get("exercises") or []
    if not exercises:
        return None
    return "; ".join(exercises)


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


# Self-relative magnitude threshold for "meaningfully negative" TSB, in SD
# units against the athlete's OWN trailing 90-day TSB distribution
# (`metrics.load.compute_tsb_zscore()`) — mirrors this project's existing
# ~1 SD convention for "a real signal, not noise" (the HRV/RHR baseline
# balanced/low split, ADR 0006/0007's noise-floor work), applied here
# instead of a borrowed absolute TSB number (none exists — ADR 0003/0007).
#
# **Real fix, 2026-08-31**: this used to be a raw-sign check ("TSB negative
# at all" — the kickoff doc's own placeholder, "TBD once load-unit
# calibration exists"). Checked against the real account (2026-08-31, 164
# days of TRIMP/Foster-based load, `metrics/strain.py`'s ADR-0008 series):
# raw TSB was negative on 97/164 days (59%) and sitting on a 17-day
# consecutive streak the day this was checked — so desensitized it barely
# functioned as a signal, sitting next to a healthy green/amber readiness
# score with no explanation of the apparent contradiction. At
# `z_threshold=1.0` with the existing 4-day window, the same real history
# fires on only 6 of 148 days with a computable z-score (4.1%) — and still
# correctly fires on the day this was checked, which really was a genuine,
# sustained load spike (BJJ + bike days stacking up), z-scores around -2 to
# -3.5 across the trailing few days, not routine noise. A documented,
# revisable default, same spirit as this project's other seed-phase numbers
# (the HRV seed thresholds, the strain saturation constant) — not a
# literature-validated number, since none exists for TSB magnitude at all.
TSB_ZSCORE_NEGATIVE_THRESHOLD = 1.0


def tsb_persistently_negative(
    tsb_series: list[tuple[str, float]],
    *,
    window_days: int = STRUCTURAL_TSB_NEGATIVE_DAYS,
    z_threshold: float = TSB_ZSCORE_NEGATIVE_THRESHOLD,
) -> bool:
    """True if each of the last `window_days` days' TSB sat at least
    `z_threshold` SD below its OWN trailing 90-day distribution, as of that
    day — the same "recompute for each of the last N days by truncating the
    series" approach `hrv_sustained_low()`/`hrv_sustained_deviation()`
    already use for HRV, applied here to `metrics.load.compute_tsb_zscore()`
    instead of a raw sign check (see the module-level constant above for the
    real-data justification for both the switch and the threshold).

    Truncates the already-computed `tsb_series` itself (not the underlying
    daily load series) at each evaluation point, rather than recomputing
    `compute_ctl_atl()` from scratch each time — equivalent, since a given
    day's TSB value never depends on later days, and simpler: `compute_tsb_
    zscore()` already only looks at its own trailing window of whatever
    series it's handed.

    A day where the z-score isn't computable yet (`confidence !=
    "full"`, e.g. still in `compute_tsb_zscore()`'s own 14-day minimum) means
    "not enough history to call this a real signal," not "confirmed calm" —
    treated as not-firing either way (design principle 6: never invent a
    reading you don't have).
    """
    if len(tsb_series) < window_days:
        return False
    for i in range(len(tsb_series) - window_days, len(tsb_series)):
        as_of = tsb_series[: i + 1]
        result = load_metrics.compute_tsb_zscore(as_of)
        if result["confidence"] != "full" or result["z_score"] is None:
            return False
        if result["z_score"] > -z_threshold:
            return False
    return True


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


# ---------------------------------------------------------------------------
# Taper (calendar-anchored to the competition date) and deload (fatigue-
# triggered, independent of the calendar) -- built 2026-08-30 after Francisco
# asked directly for both. Real sports-science research (see CLAUDE.md for
# the full evidence synthesis) confirmed these are genuinely different
# mechanisms, not the same feature at two different times: a taper is a
# planned, event-anchored reduction to peak for a known date; a deload is an
# autoregulated, fatigue-anchored reduction that should fire off real
# markers, not a fixed schedule (research finding: a scheduled,
# non-fatigue-triggered deload was neutral-to-slightly-negative in an RCT on
# a population that wasn't already run down).
# ---------------------------------------------------------------------------


def taper_day_override(config: dict[str, Any], today: str) -> dict[str, Any] | None:
    """If `today` falls within a `comp_prep.blocks[]` entry's explicit
    day-by-day `daily_schedule`, returns that day's real planned session
    instead of the generic `weekly_template` pattern.

    Real gap closed 2026-08-30: this schedule has existed in
    `config/athlete.yaml` since 2026-08-27 (Francisco's own hand-planned
    final week before competing) but nothing in this codebase ever actually
    read it — the coaching engine would have kept giving generic weekly
    guidance straight through taper week and silently missed the
    hand-planned reduction entirely.

    The taper plan is treated as authoritative, not readiness-band-
    modulated the way a normal day's `session_guidance()` output is — it
    was already deliberately built as a reduced-load week; layering a
    second, independent readiness-based reduction on top would double-
    discount it rather than express it faithfully.
    """
    for block in config.get("comp_prep", {}).get("blocks", []):
        for entry in block.get("daily_schedule", []):
            if entry["date"] == today:
                return {
                    "type": "taper",
                    "label": "Taper",
                    "instruction": entry["plan"],
                    "block_name": block["name"],
                }
    return None


def taper_status(config: dict[str, Any], today: str) -> dict[str, Any]:
    """Where `today` sits relative to the competition date and the taper
    block's own window. `days_to_competition` is always present (a simple
    countdown); `active` is only true once inside the taper block's actual
    date range (`taper_day_override()` is what actually changes that day's
    session — this is the summary/banner-level status alongside it).
    """
    comp_date = date.fromisoformat(config["goals"]["primary"]["date"])
    today_d = date.fromisoformat(today)
    taper_block = next(
        (b for b in config.get("comp_prep", {}).get("blocks", []) if b.get("name") == "taper"),
        None,
    )
    active = False
    if taper_block is not None:
        active = (
            date.fromisoformat(taper_block["starts"])
            <= today_d
            <= date.fromisoformat(taper_block["ends"])
        )
    return {
        "days_to_competition": (comp_date - today_d).days,
        "active": active,
    }


def hrv_sustained_deviation(
    hrv_observations: list[tuple[str, float]], *, window_days: int = 6
) -> bool:
    """Bidirectional version of `hrv_sustained_low()`, for the deload
    trigger specifically — NOT a replacement for the existing low-only,
    3-day session-guidance structural trigger, which stays exactly as
    kickoff doc section 7 specified it.

    Built after real research (2026-08-30) found HRV's overreaching signal
    is genuinely contested as unidirectional: Bellenger et al. 2016
    (meta-analysis, 27 studies) found overreached athletes' HRV is often
    unaffected or even INCREASED, not just decreased — Manresa-Rocamora et
    al. 2021 (meta-analysis) confirmed the same pattern. A deload trigger
    that only watches for low HRV is using a simplified, partially-
    contradicted model. `window_days` is a documented, reasoned default —
    no literature-validated number exists for this specific "should I plan
    a deload this week" decision (the one combat-sport duration found,
    Tian et al. 2013's wrestlers, describes >2 weeks for a slower, more
    severe after-the-fact NFOR diagnosis, not a preventive trigger — using
    it directly would likely be far too slow to be useful inside an 8-week
    block).
    """
    if len(hrv_observations) < window_days:
        return False
    for i in range(len(hrv_observations) - window_days, len(hrv_observations)):
        as_of = hrv_observations[: i + 1]
        result = baselines.compute_hrv_baseline(as_of)
        if result["confidence"] != "full" or result["status"] not in ("low", "high"):
            return False
    return True


def sleep_debt_elevated(debt_hours: float | None, *, threshold_hours: float) -> bool:
    """True if the rolling 14-day sleep debt (`metrics.baselines.
    compute_sleep_debt()`) exceeds `threshold_hours`. No literature-
    validated threshold exists for this as a deload trigger specifically
    (a real gap the 2026-08-30 research confirmed) — `threshold_hours` is
    read from `config/athlete.yaml: deload.sleep_debt_threshold_hours`, a
    documented reasoned default, not a literature number.
    """
    if debt_hours is None:
        return False
    return debt_hours > threshold_hours


def hooper_sustained_high(
    hooper_by_date: dict[str, float], as_of_date: str, *, window_days: int, threshold: float
) -> bool:
    """True if `window_days` consecutive CALENDAR days ending at
    `as_of_date` all have a logged `hooper_index` >= `threshold` — a gap
    (no log that day) breaks the streak, same "never invent" discipline as
    every other sustained-X check in this module.

    Built after real research (Saw, Main, Gastin 2016, systematic review)
    found subjective wellness measures are MORE sensitive and consistent
    than commonly-used objective measures for detecting training-load
    effects — this marker is deliberately NOT a tiebreaker in
    `should_deload()`, it counts the same as any objective marker.
    """
    as_of = date.fromisoformat(as_of_date)
    for i in range(window_days):
        d = (as_of - timedelta(days=i)).isoformat()
        value = hooper_by_date.get(d)
        if value is None or value < threshold:
            return False
    return True


def should_deload(
    *,
    hrv_deviation: bool,
    rhr_sustained_rise: bool,
    sleep_debt_elevated: bool,
    hooper_sustained_high: bool,
    tsb_persistently_negative: bool,
    markers_required: int = 2,
) -> dict[str, Any]:
    """Composite deload trigger — fires once at least `markers_required` of
    these 5 markers are active at once. No literature-validated "M of N"
    rule exists anywhere the 2026-08-30 research found (the one Delphi
    consensus panel that looked at this explicitly did NOT reach agreement
    on specific biomarker triggers) — this mirrors, at a larger scale, this
    project's own already-built 2-red/3-amber single-day-downgrade
    precedent (`should_downgrade_to_rest()`), a reasoned default applied
    consistently, not a borrowed literature number.

    Deliberately fatigue-triggered, never calendar-triggered (that's the
    separate `taper_status()`/`taper_day_override()` above) — research
    found a scheduled, non-fatigue-triggered deload was neutral-to-
    slightly-negative for strength in a population that wasn't already run
    down (Coleman et al. 2024 RCT), so this should only ever fire off real
    markers, never a fixed "every N weeks" schedule.

    Returns which markers fired, not just a bool — design principle 9, the
    recommendation must be traceable to its real inputs, never a black box.
    """
    markers = {
        "hrv_sustained_deviation": hrv_deviation,
        "rhr_sustained_rise": rhr_sustained_rise,
        "sleep_debt_elevated": sleep_debt_elevated,
        "hooper_sustained_high": hooper_sustained_high,
        "tsb_persistently_negative": tsb_persistently_negative,
    }
    fired = [name for name, active in markers.items() if active]
    return {
        "recommended": len(fired) >= markers_required,
        "markers_fired": fired,
        "markers_required": markers_required,
    }
