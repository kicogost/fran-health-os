from __future__ import annotations

import math
import sqlite3

import pytest

from health_os.core import db as db_module
from health_os.metrics.strain import (
    STRAIN_FOSTER_SCALE,
    STRAIN_SATURATION_K,
    StrainComponent,
    build_activity_based_load_series,
    build_daily_strain,
    build_load_by_sport_rows,
    combine_daily_strain,
    compute_foster_load,
    compute_trimp,
    estimate_max_hr,
)

_CONFIG = {"profile": {"age": 24}}


class TestEstimateMaxHr:
    def test_tanaka_formula_exact(self) -> None:
        # 208 - 0.7*age, Tanaka et al. 2001 -- exact, not approximated.
        assert estimate_max_hr(24) == pytest.approx(191.2)
        assert estimate_max_hr(40) == pytest.approx(180.0)


class TestComputeTrimp:
    def test_matches_hand_computed_value_for_a_real_session(self) -> None:
        # Francisco's real 2026-08-29 bike ride: avg_hr=143, resting_hr~49,
        # max_hr via Tanaka(24)=191.2, 107 minutes. Hand-verified separately
        # via a standalone script before writing this assertion.
        trimp = compute_trimp(avg_hr=143, resting_hr=49, max_hr=191.2, duration_min=107)
        assert trimp == pytest.approx(161.06, abs=0.01)

    def test_at_resting_hr_gives_zero_load(self) -> None:
        assert compute_trimp(avg_hr=49, resting_hr=49, max_hr=191.2, duration_min=60) == 0.0

    def test_below_resting_hr_clamps_to_zero_not_negative(self) -> None:
        # A real (if odd) case: an average below the day's resting_hr
        # reading -- shouldn't produce a negative load.
        trimp = compute_trimp(avg_hr=45, resting_hr=49, max_hr=191.2, duration_min=60)
        assert trimp == 0.0

    def test_above_max_hr_clamps_rather_than_extrapolating(self) -> None:
        at_max = compute_trimp(avg_hr=191.2, resting_hr=49, max_hr=191.2, duration_min=60)
        above_max = compute_trimp(avg_hr=210, resting_hr=49, max_hr=191.2, duration_min=60)
        assert at_max == above_max

    def test_max_hr_must_exceed_resting_hr(self) -> None:
        with pytest.raises(ValueError, match="must be greater than"):
            compute_trimp(avg_hr=100, resting_hr=100, max_hr=100, duration_min=30)

    def test_longer_duration_at_same_intensity_scales_linearly(self) -> None:
        short = compute_trimp(avg_hr=140, resting_hr=50, max_hr=190, duration_min=30)
        long_ = compute_trimp(avg_hr=140, resting_hr=50, max_hr=190, duration_min=60)
        assert long_ == pytest.approx(short * 2)


class TestComputeFosterLoad:
    def test_matches_bjj_sessions_computed_load_formula_exactly(self) -> None:
        # Must stay identical to core.models.BjjSession.computed_load's
        # formula -- duration x RPE, same units, same method.
        assert compute_foster_load(90, 8) == 720.0


class TestCombineDailyStrain:
    def test_empty_components_gives_none_not_zero(self) -> None:
        # A rest day with nothing recorded is "no data," not "confirmed
        # zero effort" (design principle 6).
        result = combine_daily_strain([])
        assert result["strain"] is None
        assert result["zone"] is None
        assert result["total_raw_load"] is None

    def test_raw_load_equal_to_k_gives_exact_closed_form_value(self) -> None:
        # Hand-verifiable exact value: at total_raw_load == K, strain
        # reduces to STRAIN_MAX * (1 - e^-1), independent of K's actual
        # magnitude -- a real closed form, not just a plausible number.
        component = StrainComponent("test", "trimp", STRAIN_SATURATION_K, "test")
        result = combine_daily_strain([component])
        # combine_daily_strain rounds to 1dp for display -- compare against
        # the same rounding, not raw floating-point precision.
        assert result["strain"] == round(21.0 * (1 - math.exp(-1)), 1)

    def test_multiple_components_sum_linearly_before_saturation(self) -> None:
        components = [
            StrainComponent("a", "trimp", 50.0, "a"),
            StrainComponent("b", "trimp", 50.0, "b"),
        ]
        result = combine_daily_strain(components)
        assert result["total_raw_load"] == pytest.approx(100.0)

    def test_two_hard_efforts_produce_less_than_double_the_strain(self) -> None:
        # The exact "compression" property WHOOP describes: doubling the
        # raw load must NOT double the displayed Strain (that's the whole
        # point of the saturating curve).
        one = combine_daily_strain([StrainComponent("a", "trimp", 150.0, "a")])
        two = combine_daily_strain(
            [StrainComponent("a", "trimp", 150.0, "a"), StrainComponent("b", "trimp", 150.0, "b")]
        )
        assert two["strain"] < one["strain"] * 2

    def test_strain_never_exceeds_max(self) -> None:
        # An enormous raw load underflows exp() to exactly 0.0, so strain
        # asymptotically reaches but never exceeds STRAIN_MAX -- <=, not <.
        huge = combine_daily_strain([StrainComponent("a", "trimp", 100_000.0, "a")])
        assert huge["strain"] <= 21.0

    def test_components_preserved_for_traceability(self) -> None:
        components = [StrainComponent("a", "trimp", 50.0, "a session")]
        result = combine_daily_strain(components)
        assert result["components"] == components


class TestStrainZone:
    def test_boundaries_match_whoops_published_bands(self) -> None:
        light = combine_daily_strain([StrainComponent("a", "trimp", 1.0, "a")])
        assert light["zone"] == "light"

        # Construct components landing near each real boundary by solving
        # the saturation formula backwards for the raw load that produces
        # a target strain just inside each band.
        def raw_for_strain(target_strain: float) -> float:
            return -STRAIN_SATURATION_K * math.log(1 - target_strain / 21.0)

        moderate = combine_daily_strain([StrainComponent("a", "trimp", raw_for_strain(11.0), "a")])
        assert moderate["zone"] == "moderate"

        high = combine_daily_strain([StrainComponent("a", "trimp", raw_for_strain(15.0), "a")])
        assert high["zone"] == "high"

        all_out = combine_daily_strain([StrainComponent("a", "trimp", raw_for_strain(19.0), "a")])
        assert all_out["zone"] == "all_out"


class TestBuildDailyStrain:
    def test_no_data_gives_none(self, conn: sqlite3.Connection) -> None:
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        assert result["strain"] is None

    def test_real_activity_with_hr_produces_trimp_component(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-30", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:1",
                "source": "garmin",
                "source_id": "1",
                "start_utc": "2026-08-30T06:00:00Z",
                "local_date": "2026-08-30",
                "sport": "cycling",
                "duration_s": 6420,
                "avg_hr": 143,
            },
            ["activity_id"],
        )
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        assert result["strain"] is not None
        assert result["components"][0].method == "trimp"

    def test_short_activity_below_duration_floor_is_ignored(self, conn: sqlite3.Connection) -> None:
        # Real motivating case: a genuine 42-second BJJ connectivity-test
        # recording exists in the real account data -- must not be treated
        # as a real session.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-30", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:2",
                "source": "garmin",
                "source_id": "2",
                "start_utc": "2026-08-30T06:00:00Z",
                "local_date": "2026-08-30",
                "sport": "other",
                "sub_sport": "bjj",
                "duration_s": 42,
                "avg_hr": 68,
            },
            ["activity_id"],
        )
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        assert result["strain"] is None

    def test_bjj_session_without_matching_activity_uses_foster_estimate(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "bjj_sessions",
            {
                "date": "2026-08-30",
                "session_type": "open_mat",
                "duration_min": 90,
                "session_rpe": 8,
            },
            ["date", "session_type"],
        )
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        assert result["strain"] is not None
        assert result["components"][0].method == "foster_estimated"

    def test_bjj_session_with_real_matching_activity_skips_foster_estimate(
        self, conn: sqlite3.Connection
    ) -> None:
        # Once a real BJJ-tagged Garmin activity exists that day (the
        # post-chest-strap case), the manual log's RPE-based estimate must
        # NOT also be added -- that would double-count one physical
        # session as two load contributions.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-30", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:3",
                "source": "garmin",
                "source_id": "3",
                "start_utc": "2026-08-30T18:00:00Z",
                "local_date": "2026-08-30",
                "sport": "other",
                "sub_sport": "bjj",
                "duration_s": 5400,
                "avg_hr": 150,
            },
            ["activity_id"],
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            {
                "date": "2026-08-30",
                "session_type": "open_mat",
                "duration_min": 90,
                "session_rpe": 8,
            },
            ["date", "session_type"],
        )
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        methods = [c.method for c in result["components"]]
        assert methods == ["trimp"]  # not ["trimp", "foster_estimated"]

    def test_missing_resting_hr_skips_hr_based_activities_entirely(
        self, conn: sqlite3.Connection
    ) -> None:
        # No daily_metrics row at all for this date -- no real HR-reserve
        # baseline to compute TRIMP against, so the activity is skipped
        # rather than computed against a borrowed/guessed resting_hr.
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:4",
                "source": "garmin",
                "source_id": "4",
                "start_utc": "2026-08-30T06:00:00Z",
                "local_date": "2026-08-30",
                "sport": "cycling",
                "duration_s": 3600,
                "avg_hr": 140,
            },
            ["activity_id"],
        )
        result = build_daily_strain(conn, "2026-08-30", _CONFIG)
        assert result["strain"] is None


class TestBuildActivityBasedLoadSeries:
    def test_no_resting_hr_anywhere_gives_empty_series(self, conn: sqlite3.Connection) -> None:
        assert build_activity_based_load_series(conn, _CONFIG, "2026-08-30") == []

    def test_walks_every_day_including_real_zero_load_days(self, conn: sqlite3.Connection) -> None:
        # A rest day between two real resting_hr readings must appear as a
        # genuine 0.0, not be skipped -- design principle 6, same "zero is a
        # real value" contract metrics/load.py's build_daily_load_series()
        # already established.
        for d in ("2026-08-28", "2026-08-29", "2026-08-30"):
            db_module.upsert(conn, "daily_metrics", {"date": d, "resting_hr": 49.0}, ["date"])
        series = build_activity_based_load_series(conn, _CONFIG, "2026-08-30")
        assert series == [
            ("2026-08-28", 0.0),
            ("2026-08-29", 0.0),
            ("2026-08-30", 0.0),
        ]

    def test_includes_bjj_manual_log_scaled(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-28", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            {
                "date": "2026-08-28",
                "session_type": "open_mat",
                "duration_min": 90,
                "session_rpe": 8,
            },
            ["date", "session_type"],
        )
        series = build_activity_based_load_series(conn, _CONFIG, "2026-08-28")
        assert series == [("2026-08-28", pytest.approx(90 * 8 * STRAIN_FOSTER_SCALE))]

    def test_matches_daily_strain_raw_load_for_the_same_date(
        self, conn: sqlite3.Connection
    ) -> None:
        # Consistency check, the whole point of the 2026-08-30 refactor:
        # this series and build_daily_strain() must never independently
        # disagree about the same date's real total raw load.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-29", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:ride1",
                "source": "garmin",
                "source_id": "ride1",
                "start_utc": "2026-08-29T06:00:00Z",
                "local_date": "2026-08-29",
                "sport": "cycling",
                "duration_s": 6420,
                "avg_hr": 143,
            },
            ["activity_id"],
        )
        strain_result = build_daily_strain(conn, "2026-08-29", _CONFIG)
        series = build_activity_based_load_series(conn, _CONFIG, "2026-08-29")
        # build_daily_strain()'s total_raw_load is rounded to 1dp for
        # display; the series returns the unrounded sum -- compare with
        # enough tolerance to absorb that rounding, not exact equality.
        assert series == [("2026-08-29", pytest.approx(strain_result["total_raw_load"], abs=0.05))]


class TestBuildLoadBySportRows:
    def test_no_data_gives_empty_list(self, conn: sqlite3.Connection) -> None:
        assert build_load_by_sport_rows(conn, _CONFIG, "2026-08-30") == []

    def test_rest_day_contributes_no_row(self, conn: sqlite3.Connection) -> None:
        # A real, computed zero must not become a fabricated "unknown: 0.0"
        # row -- design principle 6, never invent a row for nothing real.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-30", "resting_hr": 49.0}, ["date"]
        )
        assert build_load_by_sport_rows(conn, _CONFIG, "2026-08-30") == []

    def test_two_sports_same_day_produce_two_rows(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-28", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:ride1",
                "source": "garmin",
                "source_id": "ride1",
                "start_utc": "2026-08-28T06:00:00Z",
                "local_date": "2026-08-28",
                "sport": "cycling",
                "duration_s": 3600,
                "avg_hr": 140,
            },
            ["activity_id"],
        )
        db_module.upsert(
            conn,
            "bjj_sessions",
            {
                "date": "2026-08-28",
                "session_type": "open_mat",
                "duration_min": 90,
                "session_rpe": 8,
            },
            ["date", "session_type"],
        )
        rows = build_load_by_sport_rows(conn, _CONFIG, "2026-08-28")
        sports = {r["sport"] for r in rows}
        assert sports == {"cycling", "bjj"}
        assert all(r["date"] == "2026-08-28" for r in rows)

    def test_bjj_recorded_activity_labeled_bjj_not_its_raw_sport(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-28", "resting_hr": 49.0}, ["date"]
        )
        db_module.upsert(
            conn,
            "activities",
            {
                "activity_id": "garmin:bjj1",
                "source": "garmin",
                "source_id": "bjj1",
                "start_utc": "2026-08-28T18:00:00Z",
                "local_date": "2026-08-28",
                "sport": "other",
                "sub_sport": "bjj",
                "duration_s": 5400,
                "avg_hr": 150,
            },
            ["activity_id"],
        )
        rows = build_load_by_sport_rows(conn, _CONFIG, "2026-08-28")
        assert [r["sport"] for r in rows] == ["bjj"]
