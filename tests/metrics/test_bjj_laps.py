"""Tests for metrics/bjj_laps.py — HR-based sparring/rest classification of
Francisco's manually-lapped BJJ activities."""

from __future__ import annotations

import pytest

from health_os.core.models import ActivityLap
from health_os.metrics.bjj_laps import (
    LABEL_INSUFFICIENT_DATA,
    LABEL_LIKELY_REST,
    LABEL_LIKELY_SPARRING,
    LABEL_WARMUP_OR_DRILLING,
    classify_bjj_laps,
    compute_sparring_intensity,
)


def _lap(index: int, avg_hr: int | None, duration_s: float | None = None) -> ActivityLap:
    return ActivityLap(
        activity_id="garmin:1",
        lap_index=index,
        start_utc=f"2026-08-28T12:{index:02d}:00Z",
        avg_hr=avg_hr,
        duration_s=duration_s,
    )


class TestClassifyBjjLaps:
    def test_empty_input_returns_empty(self) -> None:
        assert classify_bjj_laps([]) == []

    def test_first_lap_always_warmup_or_drilling(self) -> None:
        laps = [_lap(1, 90), _lap(2, 150), _lap(3, 100)]
        result = classify_bjj_laps(laps)
        assert result[0].lap.lap_index == 1
        assert result[0].label == LABEL_WARMUP_OR_DRILLING

    def test_single_round_lap_is_insufficient_data(self) -> None:
        # Only one round lap after lap 1 -- a median split needs at least two.
        laps = [_lap(1, 90), _lap(2, 150)]
        result = classify_bjj_laps(laps)
        assert result[1].label == LABEL_INSUFFICIENT_DATA

    def test_splits_high_and_low_hr_laps_around_median_of_others(self) -> None:
        # Francisco's real workflow: lap 1 = drilling, then alternating
        # sparring (high HR) / rest (low HR) laps.
        laps = [
            _lap(1, 95),  # drilling
            _lap(2, 160),  # sparring
            _lap(3, 110),  # rest
            _lap(4, 165),  # sparring
            _lap(5, 105),  # rest
        ]
        result = classify_bjj_laps(laps)
        by_index = {r.lap.lap_index: r.label for r in result}
        assert by_index[1] == LABEL_WARMUP_OR_DRILLING
        assert by_index[2] == LABEL_LIKELY_SPARRING
        assert by_index[3] == LABEL_LIKELY_REST
        assert by_index[4] == LABEL_LIKELY_SPARRING
        assert by_index[5] == LABEL_LIKELY_REST

    def test_tie_at_median_goes_to_sparring(self) -> None:
        # Three round laps all at the same HR: each one's "others" median
        # equals its own HR exactly -- ties resolve to likely_sparring.
        laps = [_lap(1, 90), _lap(2, 140), _lap(3, 140), _lap(4, 140)]
        result = classify_bjj_laps(laps)
        assert all(r.label == LABEL_LIKELY_SPARRING for r in result[1:])

    def test_lap_with_missing_hr_is_insufficient_data_and_excluded_from_others(self) -> None:
        laps = [
            _lap(1, 95),
            _lap(2, None),  # no HR data for this lap
            _lap(3, 160),
            _lap(4, 105),
        ]
        result = classify_bjj_laps(laps)
        by_index = {r.lap.lap_index: r.label for r in result}
        assert by_index[2] == LABEL_INSUFFICIENT_DATA
        # The missing-HR lap must not pollute the median used for the others.
        assert by_index[3] == LABEL_LIKELY_SPARRING
        assert by_index[4] == LABEL_LIKELY_REST

    def test_median_round_hr_is_populated_for_classified_laps(self) -> None:
        laps = [_lap(1, 90), _lap(2, 160), _lap(3, 100)]
        result = classify_bjj_laps(laps)
        # Lap 2's "others" is just lap 3 (100) -- median of a single value is itself.
        assert result[1].median_round_hr == 100
        # Lap 3's "others" is just lap 2 (160).
        assert result[2].median_round_hr == 160

    def test_unsorted_input_is_sorted_by_lap_index_first(self) -> None:
        laps = [_lap(3, 160), _lap(1, 90), _lap(2, 100)]
        result = classify_bjj_laps(laps)
        assert [r.lap.lap_index for r in result] == [1, 2, 3]
        assert result[0].label == LABEL_WARMUP_OR_DRILLING


class TestComputeSparringIntensity:
    """`compute_sparring_intensity()` -- the sparring-only INTENSITY read,
    added 2026-08-31 after the real ground-truth check flagged that a
    whole-session Strain number can undersell the actual sparring rounds'
    intensity, then CORRECTED the same day once the first attempt (a second
    accumulated-load number on the same 0-21 Strain scale) was found to
    score those same rounds even lower than the whole session -- the wrong
    kind of metric for an intensity question. This is the replacement:
    standard Karvonen %HRR, duration-weighted across the sparring-
    classified laps, banded into standard Karvonen/Zoladz zones.
    """

    # Same alternating high/low HR pattern as
    # TestClassifyBjjLaps.test_splits_high_and_low_hr_laps_around_median_of_others
    # (laps 2 and 4 classify likely_sparring, laps 3 and 5 likely_rest) --
    # verified independently below, not assumed from that other test.
    _REALISTIC_SESSION = [
        _lap(1, 95, duration_s=3600),  # drilling, always excluded regardless of HR/duration
        _lap(2, 165, duration_s=400),  # sparring
        _lap(3, 110, duration_s=360),  # rest
        _lap(4, 172, duration_s=400),  # sparring
        _lap(5, 105, duration_s=360),  # rest
    ]

    def test_hand_verified_pct_hrr_and_zone_for_a_realistic_session(self) -> None:
        # Confirms the classification this fixture relies on before trusting
        # the %HRR result built on top of it.
        classifications = classify_bjj_laps(self._REALISTIC_SESSION)
        by_index = {c.lap.lap_index: c.label for c in classifications}
        assert by_index[2] == LABEL_LIKELY_SPARRING
        assert by_index[3] == LABEL_LIKELY_REST
        assert by_index[4] == LABEL_LIKELY_SPARRING
        assert by_index[5] == LABEL_LIKELY_REST

        result = compute_sparring_intensity(self._REALISTIC_SESSION, resting_hr=49, max_hr=191.2)
        assert result is not None
        # Hand-verified: the two likely_sparring laps (lap 2: avg_hr=165,
        # 400s; lap 4: avg_hr=172, 400s) have EQUAL duration, so the
        # duration-weighted average is just their plain mean:
        # (165 + 172) / 2 = 168.5. Karvonen %HRR against resting_hr=49,
        # max_hr=191.2 (Tanaka(24)): (168.5 - 49) / (191.2 - 49) * 100
        # = 119.5 / 142.2 * 100 = 84.0366...% -> rounds to 84.0, landing in
        # Zone 4 ("hard", >= 80%) -- clearly "hard" territory, not the
        # understated "light" the first, wrong (Strain-scale) attempt gave.
        assert result["pct_hrr"] == pytest.approx(84.0, abs=0.05)
        assert result["zone"] == 4
        assert result["zone_label"] == "hard"
        assert result["avg_hr"] == pytest.approx(168.5)
        # (400 + 400) seconds = 800s = 13.333... minutes.
        assert result["sparring_duration_min"] == pytest.approx(13.3, abs=0.05)

    def test_duration_weighting_not_a_naive_mean(self) -> None:
        # Two sparring laps of DIFFERENT length and DIFFERENT HR -- the
        # duration-weighted average must differ from (and, here, land in a
        # different zone than) the naive unweighted mean, proving the
        # duration weight is actually applied, not just computed and
        # ignored.
        laps = [
            _lap(1, 100, duration_s=1000),  # drilling
            _lap(2, 90, duration_s=300),  # rest (low, vs. others' median 165)
            _lap(3, 150, duration_s=600),  # sparring, 10 real minutes
            _lap(4, 180, duration_s=200),  # sparring, ~3.33 real minutes
        ]
        classifications = classify_bjj_laps(laps)
        by_index = {c.lap.lap_index: c.label for c in classifications}
        assert by_index[2] == LABEL_LIKELY_REST
        assert by_index[3] == LABEL_LIKELY_SPARRING
        assert by_index[4] == LABEL_LIKELY_SPARRING

        result = compute_sparring_intensity(laps, resting_hr=50, max_hr=190)
        assert result is not None
        # Duration-weighted: (150*600 + 180*200) / 800 = 157.5 -- NOT the
        # naive mean of 165, which would give a materially different (and,
        # here, differently-zoned) answer.
        assert result["avg_hr"] == pytest.approx(157.5)
        naive_mean_pct_hrr = (165 - 50) / (190 - 50) * 100  # 82.14...% -> Zone 4
        assert result["pct_hrr"] != pytest.approx(naive_mean_pct_hrr, abs=0.5)
        # Correct, duration-weighted answer: (157.5-50)/(190-50)*100 = 76.79%.
        assert result["pct_hrr"] == pytest.approx(76.8, abs=0.05)
        assert result["zone"] == 3
        assert result["zone_label"] == "moderate"
        assert result["sparring_duration_min"] == pytest.approx(13.3, abs=0.05)

    def test_zone_boundary_exactly_80_percent_hrr_lands_in_the_higher_zone(self) -> None:
        # Convention chosen (documented in metrics/bjj_laps.py: _HRR_ZONES):
        # each zone's lower bound is INCLUSIVE, so a reading landing exactly
        # ON a boundary belongs to the zone that STARTS there, not the one
        # that ends there -- 80.0% HRR is Zone 4 ("hard"), not Zone 3.
        laps = [
            _lap(1, 95, duration_s=1000),  # drilling
            _lap(2, 95, duration_s=300),  # rest (vs. the other round lap's 130)
            _lap(3, 130, duration_s=300),  # sparring, engineered to land at exactly 80% HRR
        ]
        classifications = classify_bjj_laps(laps)
        by_index = {c.lap.lap_index: c.label for c in classifications}
        assert by_index[2] == LABEL_LIKELY_REST
        assert by_index[3] == LABEL_LIKELY_SPARRING

        # resting_hr=50, max_hr=150 -> (130-50)/(150-50)*100 == 80.0 exactly.
        result = compute_sparring_intensity(laps, resting_hr=50, max_hr=150)
        assert result is not None
        assert result["pct_hrr"] == pytest.approx(80.0)
        assert result["zone"] == 4
        assert result["zone_label"] == "hard"

    def test_below_zone_1_lands_in_zone_zero_minimal_not_a_crash(self) -> None:
        # A real (if unusual) case: even the "harder" of two round laps
        # stays under 50% HRR -- must band gracefully, not crash or claim a
        # real Karvonen zone that doesn't apply.
        laps = [
            _lap(1, 70, duration_s=1000),  # drilling
            _lap(2, 65, duration_s=300),  # rest
            _lap(3, 75, duration_s=300),  # "sparring" only vs. lap 2 -- still low absolute HRR
        ]
        result = compute_sparring_intensity(laps, resting_hr=50, max_hr=190)
        assert result is not None
        assert result["zone"] == 0
        assert result["zone_label"] == "minimal"

    def test_zero_sparring_laps_returns_none(self) -> None:
        # Only one round lap after drilling -- classify_bjj_laps() can't
        # attempt a median split at all (MIN_ROUND_LAPS_FOR_SPLIT), so every
        # round lap reads insufficient_data, never likely_sparring. Never
        # invent a number in that case (design principle 6).
        laps = [_lap(1, 90), _lap(2, 150, duration_s=300)]
        assert compute_sparring_intensity(laps, resting_hr=49, max_hr=191.2) is None

    def test_empty_laps_returns_none(self) -> None:
        assert compute_sparring_intensity([], resting_hr=49, max_hr=191.2) is None

    def test_all_round_laps_missing_hr_returns_none(self) -> None:
        # Real case: no strap/watch contact for any round lap -- each reads
        # insufficient_data individually (never a guessed sparring/rest
        # split), so there is nothing real to compute a sparring number from.
        laps = [_lap(1, 90), _lap(2, None, duration_s=300), _lap(3, None, duration_s=300)]
        classifications = classify_bjj_laps(laps)
        assert all(
            c.label == LABEL_INSUFFICIENT_DATA for c in classifications if c.lap.lap_index != 1
        )
        assert compute_sparring_intensity(laps, resting_hr=49, max_hr=191.2) is None

    def test_missing_resting_hr_returns_none_not_a_crash(self) -> None:
        # %HRR cannot be computed without a real resting_hr, even though
        # the laps themselves would otherwise classify and qualify fine.
        session = self._REALISTIC_SESSION
        assert compute_sparring_intensity(session, resting_hr=None, max_hr=191.2) is None

    def test_missing_max_hr_returns_none_not_a_crash(self) -> None:
        session = self._REALISTIC_SESSION
        assert compute_sparring_intensity(session, resting_hr=49, max_hr=None) is None

    def test_sparring_lap_missing_duration_is_skipped_not_crashed(self) -> None:
        # Defensive case: classify_bjj_laps() only ever labels a lap
        # likely_sparring when avg_hr is real, but the schema still allows
        # duration_s to be NULL -- must skip that lap's contribution rather
        # than crash on `None / 60.0` or a `None`-weighted average.
        laps = [
            _lap(1, 95, duration_s=3600),
            _lap(2, 165, duration_s=None),  # sparring by HR, but no duration
            _lap(3, 110, duration_s=360),
            _lap(4, 172, duration_s=400),
            _lap(5, 105, duration_s=360),
        ]
        result = compute_sparring_intensity(laps, resting_hr=49, max_hr=191.2)
        assert result is not None
        # Only lap 4 contributes -- lap 2 is dropped for lacking duration.
        assert result["avg_hr"] == pytest.approx(172.0)
        assert result["sparring_duration_min"] == pytest.approx(400 / 60.0, abs=0.05)
