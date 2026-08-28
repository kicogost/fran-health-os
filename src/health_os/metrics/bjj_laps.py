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
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

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
