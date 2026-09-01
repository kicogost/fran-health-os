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

**Sparring intensity (added 2026-08-31, corrected same day)**:
`build_daily_strain()` also attaches a `sparring_intensity` sub-result — a
same-day INTENSITY read (not another accumulated-load number) computed only
from a BJJ activity's `likely_sparring`-classified laps (`metrics.bjj_laps.
classify_bjj_laps()`/`compute_sparring_intensity()`), shown ALONGSIDE the
whole-session Strain, never replacing it or feeding into CTL/ATL/TSB/
monotony/the weekly summary. Motivated by real MMA training-load research
(Kirk et al. 2024, *Int J Sports Physiol Perform*): segmenting a session's
internal load by activity type preserves signal a single whole-session
blended number loses — confirmed directly against Francisco's own real
2026-08-31 session, whose whole-session Strain (9.1, "light") undersold how
hard its actual sparring rounds were.

**A first attempt at this got the KIND of number wrong, not just a
constant** — the original `compute_sparring_strain()` summed TRIMP across
just the sparring laps and mapped it through this same module's saturating-
exponential-to-0-21 scale, which scored those same rounds even LOWER (4.9,
still "light") than the whole session, because TRIMP is a duration-weighted
accumulated dose and 12 minutes of sparring can never accumulate as much
dose as 90 minutes of the whole class on a scale calibrated against whole
sessions. `compute_sparring_intensity()` replaced it with the standard
Karvonen %HRR formula banded into Karvonen/Zoladz zones — see `metrics.
bjj_laps`'s module docstring for the full account.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import timedelta
from typing import Any

from health_os.core.models import ActivityLap
from health_os.metrics.bjj_laps import compute_sparring_intensity

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
    # A plain sport label for grouping -- e.g. "cycling", "bjj" -- added
    # 2026-08-30 alongside build_activity_based_load_series() below, so a
    # per-sport breakdown doesn't need to re-parse `source`'s "x:y" string.
    sport: str = "unknown"
    # Real session duration in minutes -- added 2026-08-30 alongside
    # build_weekly_summary() below, for a plain "N sessions, X hours this
    # week" stat that needs no re-parsing of `description`'s free text.
    duration_min: float = 0.0


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


def _gather_day_components(
    conn: sqlite3.Connection, date: str, config: dict[str, Any]
) -> list[StrainComponent]:
    """The actual per-day assembly: real `activities` (any sport, >= 5 real
    minutes, with a real `avg_hr`) via TRIMP, plus any `bjj_sessions` entry
    NOT already covered by a real BJJ-tagged activity that day, via Foster's
    method. Calisthenics has no separate path here -- it only contributes
    when actually recorded as a real Garmin "Strength Training" activity
    with HR (the two-signal design already established for calisthenics,
    CLAUDE.md's "Calisthenics tracking closed" section), never estimated
    from RPE alone (no duration field exists on `calisthenics_sessions` to
    run Foster's method against).

    Requires that date's own `resting_hr` -- without it there's no real
    HR-reserve baseline to compute TRIMP against, so activities that day
    are skipped entirely rather than falling back to a borrowed value.

    Extracted 2026-08-30 from what used to be `build_daily_strain()`'s own
    body, so `build_activity_based_load_series()` below can walk many days
    and get EXACTLY this same per-day answer, rather than a second,
    independently-drifting implementation of "what did today's training
    load actually consist of." One source of truth, reused by the Strain
    ring, the CTL/ATL/TSB trend, and the Training page's sport breakdown.
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
            # A BJJ activity's whole-session avg_hr/duration is used here
            # deliberately, even though `activity_laps` may hold real
            # per-round detail for the same activity (metrics/bjj_laps.py:
            # compute_sparring_intensity()) -- do NOT swap this for a
            # sparring-only lap read. Whole-session TRIMP/Foster is the sole
            # input to CTL/ATL/TSB/monotony/the weekly summary (ADR 0008;
            # both validated methods this project uses are built around
            # rating/measuring the ENTIRE session, drilling included, which
            # is real training stress). The sparring-only read is a separate,
            # same-day intensity number (not a load number at all) surfaced
            # only via `build_daily_strain()`'s `sparring_intensity` field --
            # never merged back in here.
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
                    sport="bjj" if is_bjj else (row["sport"] or "unknown"),
                    duration_min=row["duration_s"] / 60.0,
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
                    sport="bjj",
                    duration_min=row["duration_min"],
                )
            )

    return components


def build_daily_strain(
    conn: sqlite3.Connection, date: str, config: dict[str, Any]
) -> dict[str, Any]:
    """DB-facing assembly for one calendar date -- see
    `_gather_day_components()` for what actually gets gathered.

    Also attaches a `sparring_intensity` sub-result (added 2026-08-31, see
    `metrics.bjj_laps.compute_sparring_intensity()`) whenever this date's
    real BJJ activity has laps AND at least one lap classifies as
    `likely_sparring` -- `None` otherwise (a normal rest day, a non-BJJ day,
    or a BJJ day with no laps/no sparring-classified laps). This is a
    same-day %HRR/zone intensity read shown ALONGSIDE the whole-session
    accumulated-load number above -- a different KIND of number, not a
    replacement or a second value on the same scale.
    """
    result = combine_daily_strain(_gather_day_components(conn, date, config))
    result["sparring_intensity"] = _sparring_intensity_for_date(conn, date, config)
    return result


def _sparring_intensity_for_date(
    conn: sqlite3.Connection, date: str, config: dict[str, Any]
) -> dict[str, Any] | None:
    """Looks up this date's real BJJ activity (if any) and its laps, then
    delegates the actual sparring-vs-rest classification and %HRR math to
    `metrics.bjj_laps.compute_sparring_intensity()` -- reusing the SAME
    `resting_hr`/`max_hr` lookup `_gather_day_components()` already uses for
    the whole-session TRIMP call above, not a second, divergent one.

    Deliberately NOT folded into `_gather_day_components()` itself -- that
    function is also what `build_activity_based_load_series()`/
    `build_load_by_sport_rows()` walk to feed CTL/ATL/TSB/monotony/the
    weekly summary (ADR 0008), and this sparring-only number is a same-day
    intensity read (average %HRR, not a load contribution at all) -- it
    must never be summed into those series on top of the whole-session
    component that already covers the same physical laps. Keeping the
    lookup here, reachable only through `build_daily_strain()`, enforces
    that boundary by construction rather than by a comment alone.

    `metrics.bjj_laps` no longer imports anything from this module (the
    corrected `compute_sparring_intensity()` needs no Strain-scale
    machinery at all), so `compute_sparring_intensity` is imported at the
    top of this module now -- unlike the original version of this function,
    which had to defer the equivalent import to call time to break a
    two-module cycle that no longer exists.
    """
    activity_rows = conn.execute(
        "SELECT activity_id, sport, sub_sport FROM activities "
        "WHERE local_date = ? AND duration_s >= ?",
        (date, MIN_ACTIVITY_DURATION_S_FOR_STRAIN),
    ).fetchall()
    bjj_activity_ids = [
        row["activity_id"]
        for row in activity_rows
        if row["sub_sport"] == _BJJ_SUB_SPORT or row["sport"] in _BJJ_SPORT_MARKERS
    ]
    if not bjj_activity_ids:
        return None

    # In practice this account has never had more than one real BJJ activity
    # on the same date -- if that ever changes, the first one found is used
    # rather than silently combining laps across two separate sessions.
    lap_rows = conn.execute(
        "SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY lap_index",
        (bjj_activity_ids[0],),
    ).fetchall()
    if not lap_rows:
        return None

    daily_row = conn.execute(
        "SELECT resting_hr FROM daily_metrics WHERE date = ?", (date,)
    ).fetchone()
    resting_hr = daily_row["resting_hr"] if daily_row is not None else None
    if resting_hr is None:
        return None

    laps = [ActivityLap.from_row(row) for row in lap_rows]
    max_hr = estimate_max_hr(config["profile"]["age"])
    return compute_sparring_intensity(laps, resting_hr=resting_hr, max_hr=max_hr)


def _earliest_load_relevant_date(conn: sqlite3.Connection, as_of_date: str) -> str | None:
    """The earliest date this module could possibly have anything real to
    report for -- either a `resting_hr` reading (TRIMP's prerequisite) OR a
    `bjj_sessions` log (Foster's method needs no HR at all, see
    `_gather_day_components()`). Real bug caught in testing, not shipped:
    an early version anchored the walk to `resting_hr` alone, so a BJJ
    session logged for a date with no `daily_metrics` row at all (a real,
    plausible case -- Garmin sync and manual BJJ logging are independent
    habits) was silently invisible to the whole series, even though
    `_gather_day_components()` itself never required resting_hr for BJJ's
    Foster fallback.
    """
    candidates = []
    for table, date_col, extra_where in (
        ("daily_metrics", "date", "resting_hr IS NOT NULL"),
        ("bjj_sessions", "date", "1=1"),
    ):
        row = conn.execute(
            f"SELECT MIN({date_col}) AS d FROM {table} WHERE {extra_where} AND {date_col} <= ?",
            (as_of_date,),
        ).fetchone()
        if row is not None and row["d"] is not None:
            candidates.append(row["d"])
    return min(candidates) if candidates else None


def _dates_since_earliest_load_relevant_date(
    conn: sqlite3.Connection, as_of_date: str
) -> list[str]:
    """Every ISO date from `_earliest_load_relevant_date()` through
    `as_of_date`, inclusive. Shared by both activity-based-load functions
    below so they walk the identical range.
    """
    earliest = _earliest_load_relevant_date(conn, as_of_date)
    if earliest is None:
        return []

    start = date_cls.fromisoformat(earliest)
    end = date_cls.fromisoformat(as_of_date)
    dates = []
    d = start
    while d <= end:
        dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def build_activity_based_load_series(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> list[tuple[str, float]]:
    """A real, per-day training-load series -- TRIMP wherever a real
    `avg_hr` exists, Foster's method (scaled) for BJJ manual logs not
    already covered by a real matching activity -- walking every day from
    `_earliest_load_relevant_date()` (the earliest `resting_hr` OR BJJ log,
    whichever is earlier -- Foster's method needs no HR at all) through
    `as_of_date`.

    Built 2026-08-30, replacing this project's previous reliance on
    `activities.training_load` (Garmin/Strava's own, largely NULL, opaque-
    unit column -- see CLAUDE.md's training-load build-out notes) for the
    CTL/ATL/TSB trend, monotony/strain, and the Training page's sport
    breakdown. Real motivating gap: Francisco's bike rides and (once the
    HRM 600 chest strap is in use) future BJJ sessions all have a real,
    usable `avg_hr` on this account -- they just never had a Garmin/Strava-
    reported `training_load` number, which was the only thing those charts
    read before. TRIMP is the same real, cited method (Banister 1991)
    Daily Strain already uses, reused here via `_gather_day_components()`
    rather than re-derived, so the Strain ring and this series can never
    independently disagree about what a given day's real training consisted
    of.

    Every day gets a real, computed answer (possibly 0.0, a genuine "no
    HR-having activity and no BJJ log that day" result) -- this is a
    stronger guarantee than the old `training_load`-based series ever had,
    since it no longer depends on a column that's almost always NULL. Walks
    one day at a time (not a single batch query) specifically so it reuses
    `_gather_day_components()` exactly, not a second implementation of the
    same per-day logic -- personal-database scale keeps this fast (a few
    hundred small, indexed queries), verified directly rather than assumed.
    """
    return [
        (iso, sum(c.raw_load for c in _gather_day_components(conn, iso, config)))
        for iso in _dates_since_earliest_load_relevant_date(conn, as_of_date)
    ]


def build_load_by_sport_rows(
    conn: sqlite3.Connection, config: dict[str, Any], as_of_date: str
) -> list[dict[str, Any]]:
    """`{"date", "sport", "load"}` rows -- the same components
    `build_activity_based_load_series()` sums into one daily total, grouped
    by sport instead. One real day can produce more than one row (e.g. a
    ride AND a BJJ class the same day); a day with nothing real contributes
    no rows at all (never a fabricated "unknown: 0.0" row).
    """
    rows: list[dict[str, Any]] = []
    for iso in _dates_since_earliest_load_relevant_date(conn, as_of_date):
        by_sport: dict[str, float] = {}
        for c in _gather_day_components(conn, iso, config):
            by_sport[c.sport] = by_sport.get(c.sport, 0.0) + c.raw_load
        rows.extend({"date": iso, "sport": sport, "load": load} for sport, load in by_sport.items())
    return rows


DEFAULT_WEEKLY_SUMMARY_DAYS = 7


def build_weekly_summary(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    as_of_date: str,
    days: int = DEFAULT_WEEKLY_SUMMARY_DAYS,
) -> dict[str, Any]:
    """A plain, understandable "what did this week actually look like" --
    real session count and real total minutes trained, trailing `days`
    calendar days ending on `as_of_date` inclusive. Built 2026-08-30
    alongside the Training page's plain-language rework (Francisco: "no
    fluff no acronyms") as a concrete alternative to a raw "weekly load"
    number nobody but this codebase can interpret.

    Reuses `_gather_day_components()` per day -- each component already IS
    one real session (one real activity, or one BJJ manual log not already
    covered by a real activity), so counting components directly avoids
    re-deriving BJJ's own double-counting guard a second time.
    """
    end = date_cls.fromisoformat(as_of_date)
    start = end - timedelta(days=days - 1)

    session_count = 0
    total_minutes = 0.0
    by_sport: dict[str, dict[str, float]] = {}

    d = start
    while d <= end:
        for c in _gather_day_components(conn, d.isoformat(), config):
            session_count += 1
            total_minutes += c.duration_min
            sport_totals = by_sport.setdefault(c.sport, {"count": 0, "minutes": 0.0})
            sport_totals["count"] += 1
            sport_totals["minutes"] += c.duration_min
        d += timedelta(days=1)

    return {
        "days": days,
        "session_count": session_count,
        "total_minutes": total_minutes,
        "by_sport": [
            {"sport": sport, "count": int(totals["count"]), "minutes": totals["minutes"]}
            for sport, totals in sorted(by_sport.items(), key=lambda kv: -kv[1]["minutes"])
        ],
    }
