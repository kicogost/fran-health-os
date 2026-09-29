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

**`auto_detect_rounds()` (added 2026-09-29)** answers a real limitation of
everything above: it all depends on Francisco actually pressing lap at the
start of every round, and he doesn't want to be doing that while he's
sparring and focused on it. He gave the one fact that makes this tractable
without guessing: "we always do 5 minute rounds with 60 second rest" — a
FIXED, KNOWN cadence (`config/athlete.yaml: bjj_recording`), not something
that has to be inferred from scratch. So this isn't blind changepoint
detection on a noisy HR trace — it's fitting ONE free parameter (where the
known round/rest template actually starts, after however long the leading
drilling block ran) by brute-force search over candidate start times,
picking whichever one best separates "round" HR from "rest" HR across the
whole activity. Built on `ingest/garmin.py: fetch_activity_hr_stream()`'s
real, fine-grained (~1 point/3s) HR time series — a genuinely different kind
of raw input from the discrete per-lap `ActivityLap` rows the rest of this
module works from.

Same design-principle-6 discipline as `classify_bjj_laps()`'s own
`insufficient_data` gate: below `MIN_CYCLES_FOR_AUTO_DETECT` full round+rest
cycles of real data, or below `MIN_SEPARATION_BPM` of actual round-vs-rest
HR separation at the best-fitting start time, this returns an empty list
rather than a low-confidence guess dressed up as a real read. A real, stated
limitation, not glossed over: this assumes ONE clean drilling block followed
by uninterrupted round/rest cycling all the way to the end of the
recording — an unplanned extra break, a stopped-and-restarted watch, or a
genuinely irregular round length would confuse it. `compute_sparring_
intensity()`'s manual-lap path stays the ground truth whenever Francisco
does lap a session; this is the fallback for when he doesn't.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from health_os.core.models import ActivityAutoSegment, ActivityLap

MIN_ROUND_LAPS_FOR_SPLIT = 2  # need at least 2 round laps for a median split to mean anything

# `auto_detect_rounds()` defaults -- both reasoned, no literature number
# exists for either (same spirit as this project's other seed-phase
# constants, e.g. body_comp.MIN_POINTS_FOR_TREND).
MIN_CYCLES_FOR_AUTO_DETECT = 2  # need at least 2 full round+rest cycles to trust a fit
MIN_SEPARATION_BPM = 10.0  # minimum round-vs-rest HR gap before trusting the best-fit start time
_START_TIME_SEARCH_STEP_S = 15.0  # candidate start-time resolution -- cheap to search finely

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

    The result carries `"source": "manual"` (vs. `compute_auto_sparring_
    intensity()`'s `"auto_detected"`, 2026-09-29) so a caller/reader can
    always tell whether this came from Francisco's own real lap presses
    (ground truth) or a heuristic fit to the raw HR stream — never
    presented as equally certain (design principle 9).
    """
    if resting_hr is None or max_hr is None:
        return None
    if max_hr <= resting_hr:
        raise ValueError(f"max_hr ({max_hr}) must be greater than resting_hr ({resting_hr})")

    sparring_laps = [c.lap for c in classify_bjj_laps(laps) if c.label == LABEL_LIKELY_SPARRING]
    items = [
        (lap.avg_hr, lap.duration_s)
        for lap in sparring_laps
        if lap.avg_hr is not None and lap.duration_s
    ]
    result = _duration_weighted_hrr_result(items, resting_hr, max_hr)
    if result is not None:
        result["source"] = "manual"
    return result


def _duration_weighted_hrr_result(
    items: list[tuple[float, float]], resting_hr: float, max_hr: float
) -> dict[str, Any] | None:
    """The shared math behind both `compute_sparring_intensity()` (manual
    laps) and `compute_auto_sparring_intensity()` (auto-detected segments,
    2026-09-29) — `items` is a list of (avg_hr, duration_s) pairs for
    whichever "round"/"likely_sparring" units the caller already identified.
    `None` (never invented) for an empty `items` or zero total duration.
    """
    if not items:
        return None
    total_duration_s = sum(duration for _, duration in items)
    if total_duration_s <= 0:
        return None
    weighted_avg_hr = sum(hr * duration for hr, duration in items) / total_duration_s
    pct_hrr = (weighted_avg_hr - resting_hr) / (max_hr - resting_hr) * 100.0
    zone, zone_label = _hrr_zone(pct_hrr)
    return {
        "pct_hrr": round(pct_hrr, 1),
        "zone": zone,
        "zone_label": zone_label,
        "avg_hr": round(weighted_avg_hr, 1),
        "sparring_duration_min": round(total_duration_s / 60.0, 1),
    }


def compute_auto_sparring_intensity(
    segments: list[ActivityAutoSegment], resting_hr: float | None, max_hr: float | None
) -> dict[str, Any] | None:
    """Same Karvonen %HRR intensity read as `compute_sparring_intensity()`,
    for a BJJ activity Francisco did NOT manually lap — built from
    `auto_detect_rounds()`'s already-labeled segments instead. No
    classification step is needed here (unlike the manual path's
    `classify_bjj_laps()`): a segment's label is already known by
    construction from the fixed-cadence template fit, not inferred from its
    own HR level after the fact.

    Returns `None` (never invented) when `resting_hr`/`max_hr` is missing or
    no segment is labeled `"round"` (a rest day, a non-BJJ day, or a session
    `auto_detect_rounds()` couldn't confidently fit at all). Raises
    `ValueError` on `max_hr <= resting_hr`, same as the manual path.

    The result carries `"source": "auto_detected"` — see
    `compute_sparring_intensity()`'s own docstring for why this is always
    labeled, never silently presented as ground truth.
    """
    if resting_hr is None or max_hr is None:
        return None
    if max_hr <= resting_hr:
        raise ValueError(f"max_hr ({max_hr}) must be greater than resting_hr ({resting_hr})")

    items = [
        (segment.avg_hr, segment.end_s - segment.start_s)
        for segment in segments
        if segment.label == "round" and segment.avg_hr is not None
    ]
    result = _duration_weighted_hrr_result(items, resting_hr, max_hr)
    if result is not None:
        result["source"] = "auto_detected"
    return result


def auto_detect_rounds(
    activity_id: str,
    hr_stream: list[tuple[float, float]],
    round_duration_s: float,
    rest_duration_s: float,
    *,
    min_cycles: int = MIN_CYCLES_FOR_AUTO_DETECT,
    min_separation_bpm: float = MIN_SEPARATION_BPM,
) -> list[ActivityAutoSegment]:
    """Locates Francisco's known, fixed round/rest cadence
    (`round_duration_s`/`rest_duration_s`, from `config/athlete.yaml:
    bjj_recording`) directly in a BJJ activity's raw heart-rate stream
    (`ingest/garmin.py: fetch_activity_hr_stream()`'s (elapsed_seconds,
    heart_rate) pairs), for sessions he hasn't manually lapped. See the
    module docstring for the full reasoning (a template fit with one free
    parameter, not blind changepoint detection).

    Algorithm: the only real unknown is WHEN the round/rest cycling starts
    (the leading drilling/warmup block's length varies session to session,
    per his own established lapping convention where lap 1 is always
    drilling). Brute-force search over candidate start times (every
    `_START_TIME_SEARCH_STEP_S` seconds, from 0 up to the latest point that
    still leaves room for `min_cycles` full cycles) — for each candidate,
    everything from that point onward is tiled into repeating
    round/rest cycles and scored by how well it separates round-phase HR
    from rest-phase HR (mean round HR minus mean rest HR). The candidate
    with the best separation wins. This is cheap (a few hundred candidates,
    each one pass over a ~1000-2000 point stream) — no need for anything
    fancier.

    Returns `[]` (never a low-confidence guess, design principle 6) when:
    - the stream is empty;
    - the stream's total duration can't fit `min_cycles` full cycles at all;
    - even the best-fitting start time's round-vs-rest separation is below
      `min_separation_bpm` — the pattern genuinely isn't showing up clearly
      enough to trust (e.g. a continuous roll with no real rest breaks, or a
      stream too noisy/short to tell).

    Otherwise returns one `ActivityAutoSegment` per detected segment, in
    order (`segment_index` assigned sequentially starting at 0): an initial
    `"warmup_or_drilling"` segment covering everything before the detected
    start time (only if that start time is > 0), then alternating
    `"round"`/`"rest"` segments tiling from there to the end of the stream —
    the final segment is truncated to the real data available rather than
    padded out to a full `round_duration_s`/`rest_duration_s` (never
    inventing data past what was actually recorded).

    Known, stated limitation: this assumes ONE clean drilling block followed
    by uninterrupted cycling to the end. An unplanned extra break, a paused-
    and-resumed recording, or genuinely irregular round lengths would
    confuse the fit — not detected or flagged separately here, since doing
    so would need real examples of those failure modes to design against,
    which don't exist yet.
    """
    if not hr_stream:
        return []

    stream = sorted(hr_stream, key=lambda point: point[0])
    total_duration_s = stream[-1][0]
    cycle_s = round_duration_s + rest_duration_s
    min_required_s = cycle_s * min_cycles
    if total_duration_s < min_required_s:
        return []

    best_start: float | None = None
    best_separation: float | None = None
    max_start = total_duration_s - min_required_s
    start_candidate = 0.0
    while start_candidate <= max_start:
        round_hrs: list[float] = []
        rest_hrs: list[float] = []
        for t, hr in stream:
            if t < start_candidate:
                continue
            phase = (t - start_candidate) % cycle_s
            (round_hrs if phase < round_duration_s else rest_hrs).append(hr)
        if round_hrs and rest_hrs:
            separation = (sum(round_hrs) / len(round_hrs)) - (sum(rest_hrs) / len(rest_hrs))
            if best_separation is None or separation > best_separation:
                best_separation = separation
                best_start = start_candidate
        start_candidate += _START_TIME_SEARCH_STEP_S

    if best_start is None or best_separation is None or best_separation < min_separation_bpm:
        return []

    def _segment_stats(points: list[tuple[float, float]]) -> tuple[float, float] | None:
        if not points:
            return None
        hrs = [hr for _, hr in points]
        return sum(hrs) / len(hrs), max(hrs)

    segments: list[ActivityAutoSegment] = []
    segment_index = 0

    if best_start > 0:
        warmup_points = [(t, hr) for t, hr in stream if t < best_start]
        stats = _segment_stats(warmup_points)
        if stats is not None:
            avg_hr, max_hr_seen = stats
            segments.append(
                ActivityAutoSegment(
                    activity_id=activity_id,
                    segment_index=segment_index,
                    start_s=0.0,
                    end_s=best_start,
                    label="warmup_or_drilling",
                    avg_hr=avg_hr,
                    max_hr=max_hr_seen,
                )
            )
            segment_index += 1

    cycle_start = best_start
    while cycle_start < total_duration_s:
        round_end = min(cycle_start + round_duration_s, total_duration_s)
        round_points = [(t, hr) for t, hr in stream if cycle_start <= t < round_end]
        stats = _segment_stats(round_points)
        if stats is not None:
            avg_hr, max_hr_seen = stats
            segments.append(
                ActivityAutoSegment(
                    activity_id=activity_id,
                    segment_index=segment_index,
                    start_s=cycle_start,
                    end_s=round_end,
                    label="round",
                    avg_hr=avg_hr,
                    max_hr=max_hr_seen,
                )
            )
            segment_index += 1

        rest_start = round_end
        rest_end = min(cycle_start + cycle_s, total_duration_s)
        if rest_start < rest_end:
            rest_points = [(t, hr) for t, hr in stream if rest_start <= t < rest_end]
            stats = _segment_stats(rest_points)
            if stats is not None:
                avg_hr, max_hr_seen = stats
                segments.append(
                    ActivityAutoSegment(
                        activity_id=activity_id,
                        segment_index=segment_index,
                        start_s=rest_start,
                        end_s=rest_end,
                        label="rest",
                        avg_hr=avg_hr,
                        max_hr=max_hr_seen,
                    )
                )
                segment_index += 1

        cycle_start += cycle_s

    return segments
