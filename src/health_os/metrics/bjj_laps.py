"""Round-by-round classification of Francisco's manually-lapped BJJ activities
(`docs/bjj_recording_workflow.md`, `core.models.ActivityLap`).

Francisco's actual recording workflow (confirmed 2026-08-28, not assumed):
lap 1 starts at the top of class (drilling), then a new lap at the start of
each sparring round (5min work + 1min rest as one lap) or a full rest round
(6min, lapped separately) — intending sparring-vs-rest to be distinguishable
after the fact by HR level.

**This is a heuristic, not a fact from Garmin.** A real test recording showed
`intensity_type == "ACTIVE"` on every lap regardless of drilling/sparring/rest
(Garmin's `intensityType` is built for its own structured-interval workout
types, not freeform manually-pressed laps) — see `ingest/garmin.py:
fetch_activity_laps()`'s docstring. So this module derives a classification
from `avg_hr` instead, deliberately **self-relative** (each lap compared
against the median of the OTHER round laps in the same activity), the same
principle used everywhere else in this project that a personal baseline beats
a borrowed absolute threshold (HRV/RHR baselines, TSB z-score, ADR 0003) — a
fixed BPM cutoff would be wrong for one person on a bad night and wrong again
for a fitter version of the same person six months later.

Design principle 6: never invented as fact. `classify_bjj_laps()` returns a
label per lap plus an explicit `confidence`, and refuses to classify at all
below the minimum sample size rather than guessing.

`compute_sparring_intensity()` (added 2026-08-31, corrected same day) builds
on the same classification to answer a real ground-truth gap: Francisco's
first chest-strap-recorded class produced a whole-session Daily Strain of
9.1 ("light") that undersold how hard the actual sparring rounds were. The
FIRST attempt at this fix (`compute_sparring_strain()`, since removed) tried
to answer that by summing TRIMP across just the sparring laps and mapping
the result through the SAME saturating-exponential-to-0-21 scale the
whole-session Strain uses — that was the wrong kind of metric for the
question. TRIMP is a duration-weighted *accumulated dose*, and the
saturation constant is calibrated against 60-107-minute whole sessions; 12
minutes of even brutal sparring mathematically cannot accumulate as much
total dose as 90 minutes of continuous lower-intensity movement on the same
scale, so the "fix" scored the hardest rounds of the session LOWER than the
whole session (4.9 vs. 9.1 on the real 2026-08-31 data) — backwards.
Accumulated dose and intensity are different things; a second dose-scale
number was never going to honestly answer "how hard were the rounds."

`compute_sparring_intensity()` answers it instead with a genuine intensity
measure: the standard Karvonen %HRR (heart-rate-reserve) formula, duration-
weighted across the sparring-classified laps, banded into the standard
Karvonen/Zoladz training zones (Zone 1-5). This is real, published,
widely-used sports-science convention — not a bespoke formula requiring its
own calibration constant, unlike the saturating exponential it replaces.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from health_os.core.models import ActivityLap

MIN_ROUND_LAPS_FOR_SPLIT = 2  # need at least 2 round laps for a median split to mean anything

LABEL_WARMUP_OR_DRILLING = "warmup_or_drilling"
LABEL_LIKELY_SPARRING = "likely_sparring"
LABEL_LIKELY_REST = "likely_rest"
LABEL_INSUFFICIENT_DATA = "insufficient_data"


@dataclass(slots=True)
class LapClassification:
    """One lap's classification, alongside the raw lap it came from —
    `median_round_hr` is included so the result is traceable (design
    principle 9): given this and the lap's own `avg_hr`, the label is
    reproducible by hand.
    """

    lap: ActivityLap
    label: str
    median_round_hr: float | None = None


def classify_bjj_laps(laps: list[ActivityLap]) -> list[LapClassification]:
    """Classify each lap of a manually-lapped BJJ activity.

    Lap index 1 is always `warmup_or_drilling` — Francisco's own stated
    workflow starts the watch at the top of class, before any rounds, so this
    is a fixed rule, not a guess. Every lap after that ("round laps") is split
    around the median `avg_hr` of the OTHER round laps in the same activity:
    at/above the median → `likely_sparring`, below → `likely_rest`. Ties go to
    `likely_sparring` (a round exactly at the median is, if anything, more
    likely to be genuine work than a coin flip either way).

    Laps with `avg_hr is None` (no HR data for that lap — e.g. no strap/watch
    contact) are never guessed at — they get `insufficient_data` individually,
    and are excluded from the median calculation for the others.

    Returns `insufficient_data` for every round lap if fewer than
    `MIN_ROUND_LAPS_FOR_SPLIT` round laps have HR data at all — a median over
    0 or 1 values can't meaningfully separate anything, and a 2-lap workout
    (e.g. Francisco's real 2026-08-28 test recording, which was itself only a
    connectivity test, not a real class) shouldn't be dressed up as a real
    sparring-vs-rest read.

    Empty input returns an empty list.
    """
    if not laps:
        return []

    ordered = sorted(laps, key=lambda lap: lap.lap_index)
    first, rest = ordered[0], ordered[1:]

    results = [LapClassification(lap=first, label=LABEL_WARMUP_OR_DRILLING)]

    # HR by lap identity (id() — lap_index alone isn't guaranteed unique across
    # a hand-built list in tests), so "the other round laps" can be looked up
    # per-lap without a fragile parallel-list zip.
    hr_by_lap = {id(lap): lap.avg_hr for lap in rest if lap.avg_hr is not None}
    if len(hr_by_lap) < MIN_ROUND_LAPS_FOR_SPLIT:
        results.extend(LapClassification(lap=lap, label=LABEL_INSUFFICIENT_DATA) for lap in rest)
        return results

    for lap in rest:
        if lap.avg_hr is None:
            results.append(LapClassification(lap=lap, label=LABEL_INSUFFICIENT_DATA))
            continue
        # Median of the OTHER round laps, not including this one — a lap
        # shouldn't be compared against a distribution it's itself part of,
        # same reasoning as excluding the latest point from its own baseline
        # elsewhere in this project (metrics/baselines.py).
        others = [hr for key, hr in hr_by_lap.items() if key != id(lap)]
        if not others:
            # Only reachable if the outer len(hr_by_lap) >= MIN_ROUND_LAPS_FOR_SPLIT
            # gate above was satisfied by laps that all collapse to this one's
            # identity — not expected in practice, but never divide-by-median
            # of an empty list rather than assuming it can't happen.
            results.append(LapClassification(lap=lap, label=LABEL_INSUFFICIENT_DATA))
            continue
        median_hr = statistics.median(others)
        label = LABEL_LIKELY_SPARRING if lap.avg_hr >= median_hr else LABEL_LIKELY_REST
        results.append(LapClassification(lap=lap, label=label, median_round_hr=median_hr))

    return results


# Standard Karvonen/Zoladz %HRR training zones -- real, widely-cited
# sports-science convention (not invented for this project, unlike the
# STRAIN_SATURATION_K constant this replaces). Checked highest-to-lowest in
# `_hrr_zone()` below; lower bound of each band is inclusive, so a reading
# landing EXACTLY on a boundary (e.g. 80.0% HRR) belongs to the HIGHER zone
# that starts there (Zone 4, "hard"), not the lower one that ends there.
# Below 50% HRR is not a real Karvonen zone at all -- banded separately as
# zone 0 ("minimal") rather than folded into Zone 1's "very light" label,
# so the two are never confused with each other.
_HRR_ZONES: list[tuple[float, int, str]] = [
    (90.0, 5, "max"),
    (80.0, 4, "hard"),
    (70.0, 3, "moderate"),
    (60.0, 2, "light"),
    (50.0, 1, "very light"),
]


def _hrr_zone(pct_hrr: float) -> tuple[int, str]:
    """Bands a %HRR value into a (zone, zone_label) pair per `_HRR_ZONES`.
    Below 50% HRR (including negative values, e.g. an average at or below
    resting HR) falls through to zone 0, "minimal" -- graceful, not a crash
    or a mislabel as a real training zone.
    """
    for threshold, zone, label in _HRR_ZONES:
        if pct_hrr >= threshold:
            return zone, label
    return 0, "minimal"


def compute_sparring_intensity(
    laps: list[ActivityLap], resting_hr: float | None, max_hr: float | None
) -> dict[str, Any] | None:
    """A genuine INTENSITY read for ONLY the round laps `classify_bjj_laps()`
    reads as `likely_sparring` — shown ALONGSIDE the whole-session Daily
    Strain (`metrics.strain.build_daily_strain()`), a different KIND of
    number from it (average intensity, not accumulated dose), never fed
    into CTL/ATL/TSB/monotony/the weekly summary (those stay driven
    exclusively by the whole-session load series — see the comment at
    `metrics.strain._sparring_intensity_for_date()`'s call site, and ADR
    0008, for why whole-session TRIMP/Foster stays the sole periodization
    input).

    Real, evidence-backed gap this closes (Kirk et al. 2024, *Int J Sports
    Physiol Perform*, 20 MMA athletes): segmenting a session's internal load
    by activity type (sparring vs. drilling) preserves real signal a single
    whole-session blended number loses. See the module docstring for why
    the first attempt at this fix (a second, sparring-only number on the
    accumulated-load 0-21 Strain scale) was itself wrong, and why %HRR is
    the right kind of number for this question instead.

    Karvonen %HRR formula: `(avg_hr - resting_hr) / (max_hr - resting_hr) *
    100`, computed once against a single **duration-weighted average HR**
    across the sparring-classified laps (so a 6-minute hard lap and a
    6-second one don't count equally) rather than per-lap %HRR values
    averaged naively — mathematically equivalent to duration-weighting the
    per-lap %HRR values themselves, since %HRR is a linear transform of
    avg_hr for fixed resting_hr/max_hr, but computed this way so the
    intermediate `avg_hr` in the result is itself a real, traceable number
    (design principle 9), not just an internal step.

    Returns `None` (never an invented number, design principle 6) when:
    - `resting_hr` or `max_hr` is `None` — %HRR cannot be computed without
      both;
    - `classify_bjj_laps()` finds zero `likely_sparring` laps — a rest day,
      a non-BJJ day, a BJJ day with no laps at all, or a short/ambiguous
      session with too few round laps to classify at all (see
      `MIN_ROUND_LAPS_FOR_SPLIT`);
    - every sparring-classified lap is missing the `duration_s` the
      duration-weighting needs (not expected in practice: `classify_bjj_
      laps()` only ever labels a lap `likely_sparring` when it already has
      real `avg_hr`, but `duration_s` is still checked explicitly since the
      schema allows it to be `NULL`).

    Raises `ValueError` (matching `metrics.strain.compute_trimp()`'s own
    behavior for the same invalid input) if `max_hr <= resting_hr` — that's
    a data-integrity problem, not a "missing data" one, so it isn't papered
    over with a silent `None`.
    """
    if resting_hr is None or max_hr is None:
        return None
    if max_hr <= resting_hr:
        raise ValueError(f"max_hr ({max_hr}) must be greater than resting_hr ({resting_hr})")

    sparring_laps = [c.lap for c in classify_bjj_laps(laps) if c.label == LABEL_LIKELY_SPARRING]
    sparring_laps = [lap for lap in sparring_laps if lap.avg_hr is not None and lap.duration_s]
    if not sparring_laps:
        return None

    total_duration_s = sum(lap.duration_s for lap in sparring_laps)
    weighted_avg_hr = sum(lap.avg_hr * lap.duration_s for lap in sparring_laps) / total_duration_s
    pct_hrr = (weighted_avg_hr - resting_hr) / (max_hr - resting_hr) * 100.0
    zone, zone_label = _hrr_zone(pct_hrr)

    return {
        "pct_hrr": round(pct_hrr, 1),
        "zone": zone,
        "zone_label": zone_label,
        "avg_hr": round(weighted_avg_hr, 1),
        "sparring_duration_min": round(total_duration_s / 60.0, 1),
    }
