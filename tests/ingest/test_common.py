from __future__ import annotations

from health_os.ingest.common import normalize_sport_name, synthetic_source_id


class TestNormalizeSportName:
    def test_strips_hk_workout_prefix_and_snake_cases(self) -> None:
        assert normalize_sport_name("HKWorkoutActivityTypeMartialArts") == "martial_arts"

    def test_title_case_with_spaces(self) -> None:
        assert normalize_sport_name("Weight Training") == "weight_training"
        assert normalize_sport_name("Rock Climb") == "rock_climb"

    def test_simple_lowercase(self) -> None:
        assert normalize_sport_name("Ride") == "ride"
        assert normalize_sport_name("Run") == "run"

    def test_multi_word_camel_case(self) -> None:
        assert (
            normalize_sport_name("HKWorkoutActivityTypeTraditionalStrengthTraining")
            == "traditional_strength_training"
        )


class TestSyntheticSourceId:
    def test_deterministic(self) -> None:
        a = synthetic_source_id(
            "BJJBuddy", "2026-08-10 08:06:44 +0200", "2026-08-10 09:06:44 +0200"
        )
        b = synthetic_source_id(
            "BJJBuddy", "2026-08-10 08:06:44 +0200", "2026-08-10 09:06:44 +0200"
        )
        assert a == b

    def test_different_inputs_differ(self) -> None:
        a = synthetic_source_id(
            "BJJBuddy", "2026-08-10 08:06:44 +0200", "2026-08-10 09:06:44 +0200"
        )
        b = synthetic_source_id(
            "BJJBuddy", "2026-08-11 08:06:44 +0200", "2026-08-11 09:06:44 +0200"
        )
        assert a != b
