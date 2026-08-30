"""Daily Strain — a Health OS metric inspired by WHOOP's Strain concept
(0-21, saturating scale, combines cardiovascular + muscular load into one
daily number), built after Francisco asked for something "like WHOOP"
(2026-08-30) and shared WHOOP's own public explanation of how theirs works.

WHOOP's own article is explicit that the complete formula and per-input
weighting are proprietary and unpublished ("the complete proprietary
formula and weighting of each input are not published... interpret Strain
as a personalized WHOOP metric rather than a directly reproducible
physiological equation"). So this is a real, from-scratch, documented
metric in the same SPIRIT — not a claimed reproduction of WHOOP's actual
number, and this module's docstring says so rather than implying
equivalence.

Two real, published methods do the actual work, not guesses:

- **Banister TRIMP** (heart-rate-reserve method, Banister 1991) for any
  activity with a real `avg_hr` — confirmed reliable going forward: recent
  live Garmin syncs have `avg_hr` on every activity checked (2026-08-30),
  even though historical bulk-import coverage is patchy (documented
  elsewhere in CLAUDE.md). This is the SAME category of real, cited sports
  science as Foster's method (already used for BJJ load) and the Banister
  CTL/ATL/TSB model (ADR 0003) already in this codebase — not a new kind
  of assumption for this project.
- **Foster's method** (RPE x duration) for BJJ/calisthenics sessions with
  no HR data yet — the pre-chest-strap case. Once the Garmin HRM 600
  (arriving 2026-08-31) is actually worn for BJJ, those sessions get real
  `avg_hr` via the linked/matched Garmin activity and flow through TRIMP
  instead, same as any other activity — no code change needed for that
  transition, it falls out of the "TRIMP wherever avg_hr exists" rule.

Both raw loads are summed LINEARLY across the day first, then the total is
mapped through a saturating exponential onto the 0-21 display scale — this
is what produces the "compression" WHOOP describes (two hard efforts don't
roughly double Day Strain, moving from 16 to 17 takes far more than 4 to
5) without needing their private formula.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any

# Garmin sport/sub_sport values that mean "this is a BJJ session" --
# matches the same vocabulary already established in core/dedupe.py and
# CLAUDE.md's "Custom BJJ Garmin profile" section (sub_sport="bjj" for the
# custom profile once used, sport="martial_arts"/"wrestling" for the
# historical Apple-Health-sourced backfill).
_BJJ_SPORT_MARKERS = {"martial_arts", "wrestling"}
_BJJ_SUB_SPORT = "bjj"

STRAIN_MAX = 21.0

# Saturating-exponential scale constant. Derived from one real reference
# point (2026-08-30): Francisco's actual ~107min Saturday Z2/Z3 bike ride
# (avg_hr 143bpm, resting_hr ~49bpm, estimated max_hr via Tanaka) produces
# a raw TRIMP of ~161 -- chosen to land that specific real, solid-but-not-
# all-out session at Strain~15 ("High," not "All Out"), giving
# k = 161 / -ln(1 - 15/21) ~= 128.6, rounded to 130. An explicit, revisable
# calibration constant, same spirit as this project's other seed-phase
# numbers (metrics/baselines.py's HRV thresholds) -- not a black box, and
# worth refitting once more real sessions accumulate across the intensity
# range rather than one data point.
STRAIN_SATURATION_K = 130.0

# Banister's exponential weighting constant -- differs by sex in the
# original derivation (1.92 male, 1.67 female). Francisco is male.
TRIMP_EXPONENT_K = 1.92

# BJJ/calisthenics RPE*duration ("Foster") loads live on a completely
# different numeric axis than TRIMP -- today's real open-mat session
# (90min x RPE 8 = 720 raw Foster units) would swamp a TRIMP-based day
# unscaled. This brings it down to roughly the same range TRIMP produces
# for a comparably hard session. Explicitly rough: there's no real
# simultaneous HR+RPE BJJ data yet to calibrate against properly -- once
# the chest strap makes that data real, refit this against it rather than
# trusting a first-pass guess indefinitely. Deliberately a SEPARATE
# constant from config/athlete.yaml's `bjj_rpe_calibration_factor`, which
# calibrates against a different target (Garmin's own training_load,
# kickoff doc 2.4) -- conflating the two would make both harder to reason
# about later.
STRAIN_FOSTER_SCALE = 0.3

# Below this, a recorded activity is almost certainly a connectivity/watch
# test, not a real session -- real example that motivated this guard:
# a genuine 42-second "bjj"-tagged Garmin activity sits in this account's
# real data (2026-08-28's test recording, see CLAUDE.md), which would
# otherwise get treated as "the BJJ session for that day" and contribute a
# near-resting-HR TRIMP for what was actually a 90-minute class.
MIN_ACTIVITY_DURATION_S_FOR_STRAIN = 300


def estimate_max_hr(age: int) -> float:
    """Tanaka et al. (2001): 208 - 0.7*age -- more accurate than the older
    "220 - age" rule of thumb, but still a population estimate, not a
    lab-tested value (no max-HR test exists anywhere in this project's
    data). Documented as an estimate everywhere it's used, never presented
    as measured.
    """
    return 208.0 - 0.7 * age


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_trimp(avg_hr: float, resting_hr: float, max_hr: float, duration_min: float) -> float:
    """Banister's exponentially-weighted TRIMP (heart-rate-reserve method)
    -- real, published sports science, not invented. `hr_reserve_fraction`
    is 0 at resting HR, 1 at max HR (clamped -- a reading at or below
    resting HR contributes zero load, one at or above max HR is capped at
    the max-HR weighting rather than extrapolating past it).
    """
    if max_hr <= resting_hr:
        raise ValueError(f"max_hr ({max_hr}) must be greater than resting_hr ({resting_hr})")
    hr_reserve_fraction = _clamp((avg_hr - resting_hr) / (max_hr - resting_hr), 0.0, 1.0)
    return (
        duration_min * hr_reserve_fraction * 0.64 * math.exp(TRIMP_EXPONENT_K * hr_reserve_fraction)
    )


def compute_foster_load(duration_min: float, session_rpe: float) -> float:
    """Foster's session-RPE method -- duration x RPE. Identical formula to
    `core.models.BjjSession.computed_load` (not reimplemented differently
    here by accident -- same method, same units, deliberately consistent).
    """
    return duration_min * session_rpe


@dataclass(slots=True)
class StrainComponent:
    """One contributor to a day's total Strain -- always kept alongside the
    combined result (design principle 9: every derived number traceable to
    its inputs), never collapsed away after the sum.
    """

    source: str  # e.g. "garmin:cycling", "bjj_manual:open_mat"
    method: str  # "trimp" | "foster_estimated"
    raw_load: float
    description: str


def combine_daily_strain(components: list[StrainComponent]) -> dict[str, Any]:
    """Sums raw loads linearly, then maps the total through a saturating
    exponential onto 0-21 -- the "each additional point is harder to earn"
    shape WHOOP describes, via a documented formula rather than WHOOP's own
    unpublished one. Returns `strain=None` (never 0.0) when there's
    genuinely nothing to combine -- a rest day with zero components is
    "no data," not "confirmed zero effort" (design principle 6).
    """
    if not components:
        return {"strain": None, "zone": None, "components": [], "total_raw_load": None}

    total_raw = sum(c.raw_load for c in components)
    strain = STRAIN_MAX * (1.0 - math.exp(-total_raw / STRAIN_SATURATION_K))
    return {
        "strain": round(strain, 1),
        "zone": _strain_zone(strain),
        "components": components,
        "total_raw_load": round(total_raw, 1),
    }


def _strain_zone(strain: float) -> str:
    """WHOOP's own published band boundaries (0-9 light, 10-13 moderate,
    14-17 high, 18-21 all_out) -- these ARE public even though the formula
    behind the number isn't, so reused directly rather than re-invented.
    """
    if strain < 10.0:
        return "light"
    if strain < 14.0:
        return "moderate"
    if strain < 18.0:
        return "high"
    return "all_out"


def build_daily_strain(
    conn: sqlite3.Connection, date: str, config: dict[str, Any]
) -> dict[str, Any]:
    """DB-facing assembly for one calendar date: real `activities` (any
    sport, >= 5 real minutes, with a real `avg_hr`) via TRIMP, plus any
    `bjj_sessions` entry NOT already covered by a real BJJ-tagged activity
    that day, via Foster's method. Calisthenics has no separate path here
    -- it only contributes when actually recorded as a real Garmin
    "Strength Training" activity with HR (the two-signal design already
    established for calisthenics, CLAUDE.md's "Calisthenics tracking
    closed" section), never estimated from RPE alone (no duration field
    exists on `calisthenics_sessions` to run Foster's method against).

    Requires that date's own `resting_hr` -- without it there's no real
    HR-reserve baseline to compute TRIMP against, so activities that day
    are skipped entirely rather than falling back to a borrowed value.
    """
    daily_row = conn.execute(
        "SELECT resting_hr FROM daily_metrics WHERE date = ?", (date,)
    ).fetchone()
    resting_hr = daily_row["resting_hr"] if daily_row is not None else None

    activity_rows = conn.execute(
        "SELECT source, sport, sub_sport, duration_s, avg_hr FROM activities "
        "WHERE local_date = ? AND duration_s >= ?",
        (date, MIN_ACTIVITY_DURATION_S_FOR_STRAIN),
    ).fetchall()

    components: list[StrainComponent] = []
    bjj_covered_by_activity = False
    max_hr = estimate_max_hr(config["profile"]["age"])

    if resting_hr is not None:
        for row in activity_rows:
            is_bjj = row["sub_sport"] == _BJJ_SUB_SPORT or row["sport"] in _BJJ_SPORT_MARKERS
            if row["avg_hr"] is None:
                continue
            trimp = compute_trimp(
                avg_hr=row["avg_hr"],
                resting_hr=resting_hr,
                max_hr=max_hr,
                duration_min=row["duration_s"] / 60.0,
            )
            components.append(
                StrainComponent(
                    source=f"{row['source']}:{row['sport']}",
                    method="trimp",
                    raw_load=trimp,
                    description=f"{row['sport']} ({row['duration_s'] / 60:.0f} min, "
                    f"avg HR {row['avg_hr']:.0f})",
                )
            )
            if is_bjj:
                bjj_covered_by_activity = True

    if not bjj_covered_by_activity:
        bjj_rows = conn.execute(
            "SELECT session_type, duration_min, session_rpe FROM bjj_sessions WHERE date = ?",
            (date,),
        ).fetchall()
        for row in bjj_rows:
            foster = (
                compute_foster_load(row["duration_min"], row["session_rpe"]) * STRAIN_FOSTER_SCALE
            )
            components.append(
                StrainComponent(
                    source=f"bjj_manual:{row['session_type']}",
                    method="foster_estimated",
                    raw_load=foster,
                    description=f"{row['session_type']} ({row['duration_min']} min, "
                    f"RPE {row['session_rpe']}) -- no HR data, estimated from RPE",
                )
            )

    return combine_daily_strain(components)
