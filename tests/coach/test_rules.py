from __future__ import annotations

from health_os.coach.rules import (
    calisthenics_exercise_breakdown,
    classify_readiness_band,
    has_recent_neck_niggle,
    hooper_sustained_high,
    hrv_sustained_deviation,
    hrv_sustained_low,
    monotony_strain_flag,
    nutrition_focus,
    scheduled_sessions_for,
    session_guidance,
    should_deload,
    should_downgrade_to_rest,
    sleep_debt_elevated,
    taper_day_override,
    taper_status,
    tsb_persistently_negative,
)

_MINIMAL_CONFIG = {
    "comp_prep": {
        "weekly_template": [
            {
                "day": "monday",
                "sessions": [
                    {"type": "bjj", "subtype": "no_gi_technical"},
                    {"type": "calisthenics", "subtype": "strength_a"},
                ],
            },
            {"day": "thursday", "sessions": [{"type": "rest"}]},
            {"day": "friday", "sessions": [{"type": "bjj", "subtype": "open_mat"}]},
        ]
    },
    "nutrition": {"protein_g_daily_min": 180},
}


class TestClassifyReadinessBand:
    def test_none_is_no_data(self) -> None:
        assert classify_readiness_band(None) == "no_data"

    def test_boundaries(self) -> None:
        assert classify_readiness_band(75.0) == "green"
        assert classify_readiness_band(74.9) == "amber"
        assert classify_readiness_band(55.0) == "amber"
        assert classify_readiness_band(54.9) == "red"
        assert classify_readiness_band(0.0) == "red"
        assert classify_readiness_band(100.0) == "green"


class TestScheduledSessionsFor:
    def test_finds_matching_day(self) -> None:
        sessions = scheduled_sessions_for(_MINIMAL_CONFIG, "monday")
        assert len(sessions) == 2
        assert sessions[0]["type"] == "bjj"

    def test_unknown_day_returns_empty(self) -> None:
        assert scheduled_sessions_for(_MINIMAL_CONFIG, "someday") == []

    def test_rest_day(self) -> None:
        assert scheduled_sessions_for(_MINIMAL_CONFIG, "thursday") == [{"type": "rest"}]


class TestHasRecentNeckNiggle:
    def test_finds_neck_case_insensitive(self) -> None:
        assert has_recent_neck_niggle(["left knee tight", "Neck a bit stiff"])

    def test_no_match(self) -> None:
        assert not has_recent_neck_niggle(["left knee tight", None, ""])

    def test_empty_list(self) -> None:
        assert not has_recent_neck_niggle([])


class TestSessionGuidance:
    def test_known_session_band_combo(self) -> None:
        session = {"type": "bjj", "subtype": "open_mat"}
        assert "Cap it" in session_guidance(session, "amber")
        assert "Go hard" in session_guidance(session, "green")
        assert "Drilling only" in session_guidance(session, "red")

    def test_rest_session(self) -> None:
        assert "rest" in session_guidance({"type": "rest"}, "green").lower()

    def test_no_data_band_ignores_session_type(self) -> None:
        result = session_guidance({"type": "bjj", "subtype": "open_mat"}, "no_data")
        assert "go by feel" in result.lower()

    def test_unknown_session_type_does_not_crash(self) -> None:
        result = session_guidance({"type": "yoga"}, "green")
        assert "no guidance rule" in result.lower()

    def test_neck_niggle_overrides_calisthenics_regardless_of_band(self) -> None:
        session = {"type": "calisthenics", "subtype": "strength_a"}
        for band in ("green", "amber", "red"):
            result = session_guidance(session, band, recent_neck_niggle=True)
            assert "neck niggle" in result.lower()
            assert "hold current load" in result.lower()

    def test_neck_niggle_does_not_affect_non_calisthenics(self) -> None:
        session = {"type": "bjj", "subtype": "open_mat"}
        result = session_guidance(session, "green", recent_neck_niggle=True)
        assert "neck" not in result.lower()

    def test_without_neck_niggle_calisthenics_gets_normal_guidance(self) -> None:
        session = {"type": "calisthenics", "subtype": "strength_a"}
        result = session_guidance(session, "green", recent_neck_niggle=False)
        assert "progression" in result.lower()


class TestCalisthenicsExerciseBreakdown:
    _CONFIG = {
        "comp_prep": {
            "strength_sessions": {
                "strength_a": {
                    "exercises": [
                        "weighted or slow-tempo pull-ups: 4x5 (superset with next)",
                        "pseudo-planche push-ups: 3x8",
                    ]
                },
                "strength_b": {"exercises": []},
                "no_exercises_key": {"day": "monday"},
            }
        }
    }

    def test_matching_subtype_joins_exercises(self) -> None:
        result = calisthenics_exercise_breakdown(self._CONFIG, "strength_a")
        assert result == (
            "weighted or slow-tempo pull-ups: 4x5 (superset with next); "
            "pseudo-planche push-ups: 3x8"
        )

    def test_unknown_subtype_returns_none_not_invented(self) -> None:
        # Design principle 6: never invent data -- e.g. a holiday-week
        # substitution logged under a subtype with no config entry at all.
        assert calisthenics_exercise_breakdown(self._CONFIG, "push_and_abs_holiday") is None

    def test_empty_exercises_list_returns_none(self) -> None:
        assert calisthenics_exercise_breakdown(self._CONFIG, "strength_b") is None

    def test_subtype_present_but_no_exercises_key_returns_none(self) -> None:
        assert calisthenics_exercise_breakdown(self._CONFIG, "no_exercises_key") is None

    def test_none_subtype_returns_none(self) -> None:
        assert calisthenics_exercise_breakdown(self._CONFIG, None) is None

    def test_missing_strength_sessions_config_does_not_crash(self) -> None:
        assert calisthenics_exercise_breakdown({}, "strength_a") is None

    def test_against_the_real_config_shape(self) -> None:
        # Verified 2026-08-31 against the actual config/athlete.yaml: real
        # exercise entries never contain a semicolon, so "; " is an
        # unambiguous separator -- locked in here so a future exercise
        # string containing one would be caught by this test failing to
        # round-trip cleanly, not silently.
        config = {
            "comp_prep": {
                "strength_sessions": {
                    "strength_b": {
                        "exercises": [
                            "dips, weighted if bodyweight is easy: 4x6",
                            "Copenhagen plank: 3x20s/side (adductors — guard retention transfer)",
                        ]
                    }
                }
            }
        }
        result = calisthenics_exercise_breakdown(config, "strength_b")
        assert result is not None
        assert result.count("; ") == 1
        assert ";" not in result.replace("; ", "")


class TestShouldDowngradeToRest:
    def test_two_consecutive_red_triggers(self) -> None:
        assert should_downgrade_to_rest(["green", "red", "red"])

    def test_two_red_not_consecutive_does_not_trigger(self) -> None:
        assert not should_downgrade_to_rest(["red", "green", "red"])

    def test_three_amber_triggers(self) -> None:
        assert should_downgrade_to_rest(["amber", "amber", "amber"])

    def test_two_amber_one_green_does_not_trigger(self) -> None:
        assert not should_downgrade_to_rest(["amber", "amber", "green"])

    def test_single_red_does_not_trigger(self) -> None:
        assert not should_downgrade_to_rest(["green", "green", "red"])

    def test_short_history_does_not_crash(self) -> None:
        assert not should_downgrade_to_rest(["red"])
        assert not should_downgrade_to_rest([])


class TestHrvSustainedLow:
    def _dated(self, values: list[float]) -> list[tuple[str, float]]:
        from datetime import date, timedelta

        start = date(2026, 1, 1)
        return [((start + timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]

    def test_insufficient_history_is_false(self) -> None:
        assert not hrv_sustained_low(self._dated([90.0, 90.0]))

    def test_three_consecutive_low_days_triggers(self) -> None:
        # 60 stable days at 90, then 3 days clearly low (>1 SD below median).
        values = [90.0] * 60 + [70.0, 68.0, 65.0]
        assert hrv_sustained_low(self._dated(values))

    def test_only_two_low_days_does_not_trigger(self) -> None:
        values = [90.0] * 60 + [90.0, 68.0, 65.0]
        assert not hrv_sustained_low(self._dated(values))

    def test_stable_history_does_not_trigger(self) -> None:
        assert not hrv_sustained_low(self._dated([90.0] * 63))


class TestTsbPersistentlyNegative:
    """Rewritten 2026-08-31: this trigger switched from a raw-sign check
    ("TSB negative at all") to a self-relative z-score check
    (`metrics.load.compute_tsb_zscore()`, >= 1 SD below the athlete's own
    trailing 90-day TSB distribution, for `window_days` days straight) —
    see `coach/rules.py: TSB_ZSCORE_NEGATIVE_THRESHOLD`'s docstring for the
    real-data justification (the old check fired on 59% of real days / a
    17-day streak; the new one fires on ~4% of the same real history).
    """

    @staticmethod
    def _dated(values: list[float]) -> list[tuple[str, float]]:
        return [(f"d{i:03d}", v) for i, v in enumerate(values)]

    def test_insufficient_days_is_false(self) -> None:
        assert not tsb_persistently_negative([("d0", -5.0), ("d1", -5.0)])

    def test_mildly_negative_every_day_does_not_trigger(self) -> None:
        # 30 days oscillating around -5 (mean -5, small noise) -- every
        # single day is "negative" under the old raw-sign check, but none of
        # the last 4 days sits >= 1 SD below ITS OWN trailing distribution
        # (hand-verified: the last 4 days' z-scores are -1.22, 0.0, +1.19,
        # -1.22 -- one day is even ABOVE its own recent mean). This is
        # exactly the real-world case the old check got wrong: routine
        # noise around a stable, mildly-negative level, not real
        # accumulating fatigue.
        mild = [-5.0, -4.0, -6.0, -5.0, -4.0, -6.0] * 5
        series = self._dated(mild)
        assert not tsb_persistently_negative(series)

    def test_genuine_sustained_deep_dip_triggers(self) -> None:
        # 30 days oscillating near 0 (mean 0, small noise, an established
        # "normal" range), then a real, sustained deep dip for the last 4
        # days -- a genuine multi-day fatigue spike, not noise. Hand-
        # verified z-scores for the last 4 days: -5.42, -3.98, -2.91, -2.80
        # -- all comfortably past the 1 SD threshold every single day.
        stable = [0.0, 1.0, -1.0, 0.0, 1.0, -1.0] * 5
        dip_tail = [-30.0, -32.0, -28.0, -31.0]
        series = self._dated(stable + dip_tail)
        assert tsb_persistently_negative(series)

    def test_one_day_recovering_above_threshold_breaks_the_streak(self) -> None:
        # Same deep-dip setup as above, but the 3rd of the 4 days recovers
        # to within 1 SD of normal (a real one-day rebound) -- the
        # "sustained" requirement means this must NOT trigger, same
        # discipline as hrv_sustained_low()'s "one day breaks it".
        stable = [0.0, 1.0, -1.0, 0.0, 1.0, -1.0] * 5
        dip_tail = [-30.0, -32.0, 0.5, -31.0]
        series = self._dated(stable + dip_tail)
        assert not tsb_persistently_negative(series)

    def test_constant_series_has_undefined_variance_and_does_not_trigger(self) -> None:
        # All-identical TSB values -> compute_tsb_zscore()'s own SD is zero
        # ("undefined_zero_variance", not "full") -- treated as not-firing,
        # same "don't invent a reading you don't have" rule as everywhere
        # else, not a fabricated "very high" z-score.
        series = [(f"d{i:03d}", -5.0) for i in range(20)]
        assert not tsb_persistently_negative(series)


class TestMonotonyStrainFlag:
    def test_insufficient_data_is_false(self) -> None:
        assert not monotony_strain_flag([(f"d{i}", 100.0) for i in range(5)])

    def test_high_monotony_and_top_quartile_strain_triggers(self) -> None:
        # 8 weeks of low-variance load (constant-ish, high monotony), with
        # the load level ramping up week to week so the LAST week's strain
        # (load-magnitude-driven) is the highest of the 8 -- top quartile by
        # construction.
        series = []
        for week in range(8):
            base = 100.0 + week * 20.0  # ramps up -> last week has highest strain
            series.extend(
                [(f"w{week}d{d}", base + (1.0 if d % 2 == 0 else -1.0)) for d in range(7)]
            )
        assert monotony_strain_flag(series)

    def test_low_monotony_week_does_not_trigger(self) -> None:
        # High day-to-day variance -> monotony well under 2.0.
        series = [(f"d{i}", 200.0 if i % 2 == 0 else 10.0) for i in range(56)]
        assert not monotony_strain_flag(series)


class TestNutritionFocus:
    def test_default_message(self) -> None:
        result = nutrition_focus(_MINIMAL_CONFIG)
        assert "180g protein" in result

    def test_social_meal_message_never_suggests_compensating(self) -> None:
        result = nutrition_focus(_MINIMAL_CONFIG, yesterday_social_meal=True)
        assert "no compensating" in result.lower()
        assert "180g protein" in result

    def test_no_social_meal_gets_default(self) -> None:
        result = nutrition_focus(_MINIMAL_CONFIG, yesterday_social_meal=False)
        assert "no compensating" not in result.lower()


_TAPER_CONFIG = {
    "goals": {"primary": {"date": "2026-10-18"}},
    "comp_prep": {
        "blocks": [
            {"name": "build", "starts": "2026-09-07", "ends": "2026-09-27"},
            {
                "name": "taper",
                "starts": "2026-10-12",
                "ends": "2026-10-18",
                "daily_schedule": [
                    {"date": "2026-10-12", "day": "monday", "plan": "BJJ, technical, 60% effort"},
                    {"date": "2026-10-18", "day": "sunday", "plan": "COMPETE"},
                ],
            },
        ]
    },
}


class TestTaperDayOverride:
    def test_finds_a_real_scheduled_taper_day(self) -> None:
        override = taper_day_override(_TAPER_CONFIG, "2026-10-12")
        assert override == {
            "type": "taper",
            "label": "Taper",
            "instruction": "BJJ, technical, 60% effort",
            "block_name": "taper",
        }

    def test_date_outside_any_daily_schedule_returns_none(self) -> None:
        assert taper_day_override(_TAPER_CONFIG, "2026-09-15") is None

    def test_date_before_taper_block_returns_none(self) -> None:
        # Real regression this guards: only an EXACT daily_schedule date
        # entry should match, not "anytime on or after the block starts."
        assert taper_day_override(_TAPER_CONFIG, "2026-10-11") is None

    def test_missing_blocks_key_does_not_crash(self) -> None:
        assert taper_day_override({"comp_prep": {}}, "2026-10-12") is None


class TestTaperStatus:
    def test_days_to_competition_counts_down(self) -> None:
        status = taper_status(_TAPER_CONFIG, "2026-10-08")
        assert status["days_to_competition"] == 10
        assert status["active"] is False

    def test_active_true_inside_taper_block_window(self) -> None:
        status = taper_status(_TAPER_CONFIG, "2026-10-15")
        assert status["active"] is True
        assert status["days_to_competition"] == 3

    def test_active_true_on_competition_day_itself(self) -> None:
        status = taper_status(_TAPER_CONFIG, "2026-10-18")
        assert status["active"] is True
        assert status["days_to_competition"] == 0

    def test_no_taper_block_defined_gives_inactive_but_still_counts_down(self) -> None:
        config = {"goals": {"primary": {"date": "2026-10-18"}}, "comp_prep": {"blocks": []}}
        status = taper_status(config, "2026-10-01")
        assert status["active"] is False
        assert status["days_to_competition"] == 17


class TestHrvSustainedDeviation:
    def _dated(self, values: list[float]) -> list[tuple[str, float]]:
        from datetime import date, timedelta

        start = date(2026, 1, 1)
        return [((start + timedelta(days=i)).isoformat(), v) for i, v in enumerate(values)]

    def test_sustained_high_triggers_not_just_low(self) -> None:
        # The real fix this function exists for: hrv_sustained_low() would
        # miss this entirely (it only ever checks for "low").
        values = [90.0] * 60 + [115.0] * 6
        assert hrv_sustained_deviation(self._dated(values), window_days=6)

    def test_sustained_low_still_triggers(self) -> None:
        values = [90.0] * 60 + [65.0] * 6
        assert hrv_sustained_deviation(self._dated(values), window_days=6)

    def test_stable_history_does_not_trigger(self) -> None:
        assert not hrv_sustained_deviation(self._dated([90.0] * 66), window_days=6)

    def test_insufficient_history_is_false(self) -> None:
        assert not hrv_sustained_deviation(self._dated([90.0] * 3), window_days=6)


class TestSleepDebtElevated:
    def test_above_threshold_triggers(self) -> None:
        assert sleep_debt_elevated(8.0, threshold_hours=7.0)

    def test_at_threshold_does_not_trigger(self) -> None:
        assert not sleep_debt_elevated(7.0, threshold_hours=7.0)

    def test_below_threshold_does_not_trigger(self) -> None:
        assert not sleep_debt_elevated(3.0, threshold_hours=7.0)

    def test_none_is_false_not_a_crash(self) -> None:
        assert not sleep_debt_elevated(None, threshold_hours=7.0)

    def test_negative_debt_surplus_does_not_trigger(self) -> None:
        assert not sleep_debt_elevated(-2.0, threshold_hours=7.0)


class TestHooperSustainedHigh:
    def test_consecutive_high_days_triggers(self) -> None:
        by_date = {"2026-08-28": 25.0, "2026-08-29": 24.0, "2026-08-30": 30.0}
        assert hooper_sustained_high(by_date, "2026-08-30", window_days=3, threshold=22.0)

    def test_a_gap_day_breaks_the_streak(self) -> None:
        # 2026-08-29 has no log at all -- never invented as "probably fine."
        by_date = {"2026-08-28": 25.0, "2026-08-30": 30.0}
        assert not hooper_sustained_high(by_date, "2026-08-30", window_days=3, threshold=22.0)

    def test_one_day_below_threshold_breaks_the_streak(self) -> None:
        by_date = {"2026-08-28": 25.0, "2026-08-29": 10.0, "2026-08-30": 30.0}
        assert not hooper_sustained_high(by_date, "2026-08-30", window_days=3, threshold=22.0)

    def test_exactly_at_threshold_counts(self) -> None:
        by_date = {"2026-08-28": 22.0, "2026-08-29": 22.0, "2026-08-30": 22.0}
        assert hooper_sustained_high(by_date, "2026-08-30", window_days=3, threshold=22.0)


class TestShouldDeload:
    def test_two_markers_triggers_by_default(self) -> None:
        result = should_deload(
            hrv_deviation=True,
            rhr_sustained_rise=True,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=False,
        )
        assert result["recommended"] is True
        assert set(result["markers_fired"]) == {"hrv_sustained_deviation", "rhr_sustained_rise"}

    def test_one_marker_does_not_trigger_by_default(self) -> None:
        result = should_deload(
            hrv_deviation=True,
            rhr_sustained_rise=False,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=False,
        )
        assert result["recommended"] is False
        assert result["markers_fired"] == ["hrv_sustained_deviation"]

    def test_no_markers_reports_empty_list_not_none(self) -> None:
        result = should_deload(
            hrv_deviation=False,
            rhr_sustained_rise=False,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=False,
        )
        assert result["markers_fired"] == []
        assert result["recommended"] is False

    def test_markers_required_is_configurable(self) -> None:
        result = should_deload(
            hrv_deviation=True,
            rhr_sustained_rise=True,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=False,
            markers_required=3,
        )
        assert result["recommended"] is False

    def test_all_five_markers_fire_together(self) -> None:
        result = should_deload(
            hrv_deviation=True,
            rhr_sustained_rise=True,
            sleep_debt_elevated=True,
            hooper_sustained_high=True,
            tsb_persistently_negative=True,
        )
        assert len(result["markers_fired"]) == 5
        assert result["recommended"] is True

    def test_new_tsb_trigger_plus_one_other_marker_still_recommends_deload(self) -> None:
        # End-to-end wiring check, not just the isolated bool: a genuinely
        # deep, sustained TSB dip (same series as
        # TestTsbPersistentlyNegative.test_genuine_sustained_deep_dip_triggers)
        # feeds tsb_persistently_negative() for real, and combined with one
        # other real marker still clears the "2 of 5" gate exactly as before
        # the z-score rewrite -- the gate itself didn't need to change, only
        # what counts as the TSB marker being true.
        stable = [0.0, 1.0, -1.0, 0.0, 1.0, -1.0] * 5
        dip_tail = [-30.0, -32.0, -28.0, -31.0]
        series = TestTsbPersistentlyNegative._dated(stable + dip_tail)
        tsb_flag = tsb_persistently_negative(series)
        assert tsb_flag is True

        result = should_deload(
            hrv_deviation=False,
            rhr_sustained_rise=True,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=tsb_flag,
        )
        assert result["recommended"] is True
        assert set(result["markers_fired"]) == {"rhr_sustained_rise", "tsb_persistently_negative"}

    def test_only_mildly_negative_tsb_alone_does_not_reach_the_gate(self) -> None:
        # The routine-noise case from TestTsbPersistentlyNegative -- real
        # data that would have counted as a fired marker under the old
        # raw-sign check -- correctly contributes nothing here now, so a
        # second real marker firing alone (below markers_required=2) does
        # not recommend a deload.
        mild = [-5.0, -4.0, -6.0, -5.0, -4.0, -6.0] * 5
        series = TestTsbPersistentlyNegative._dated(mild)
        tsb_flag = tsb_persistently_negative(series)
        assert tsb_flag is False

        result = should_deload(
            hrv_deviation=False,
            rhr_sustained_rise=True,
            sleep_debt_elevated=False,
            hooper_sustained_high=False,
            tsb_persistently_negative=tsb_flag,
        )
        assert result["recommended"] is False
        assert result["markers_fired"] == ["rhr_sustained_rise"]
