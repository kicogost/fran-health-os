"""Tests for metrics/bjj_laps.py — HR-based sparring/rest classification of
Francisco's manually-lapped BJJ activities."""

from __future__ import annotations

from health_os.core.models import ActivityLap
from health_os.metrics.bjj_laps import (
    LABEL_INSUFFICIENT_DATA,
    LABEL_LIKELY_REST,
    LABEL_LIKELY_SPARRING,
    LABEL_WARMUP_OR_DRILLING,
    classify_bjj_laps,
)


def _lap(index: int, avg_hr: int | None) -> ActivityLap:
    return ActivityLap(
        activity_id="garmin:1",
        lap_index=index,
        start_utc=f"2026-08-28T12:{index:02d}:00Z",
        avg_hr=avg_hr,
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
