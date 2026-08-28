from __future__ import annotations

from health_os.coach.rules import (
    classify_readiness_band,
    has_recent_neck_niggle,
    hrv_sustained_low,
    monotony_strain_flag,
    nutrition_focus,
    scheduled_sessions_for,
    session_guidance,
    should_downgrade_to_rest,
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
    def test_four_negative_days_triggers(self) -> None:
        series = [(f"d{i}", -5.0) for i in range(4)]
        assert tsb_persistently_negative(series)

    def test_one_positive_day_breaks_it(self) -> None:
        series = [("d0", -5.0), ("d1", -5.0), ("d2", 1.0), ("d3", -5.0)]
        assert not tsb_persistently_negative(series)

    def test_insufficient_days_is_false(self) -> None:
        assert not tsb_persistently_negative([("d0", -5.0), ("d1", -5.0)])

    def test_zero_is_not_negative(self) -> None:
        series = [(f"d{i}", 0.0) for i in range(4)]
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
