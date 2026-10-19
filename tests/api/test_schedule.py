from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from health_os.api.main import app
from health_os.api.schedule import WEEKDAYS, build_schedule_payload, validate_routine

REAL_CONFIG = Path(__file__).parents[2] / "config" / "athlete.yaml"


def _config(routine: dict) -> dict:
    return {"weekly_architecture": {"starts": "2026-10-19", "daily_routine": routine}}


def _routine(**overrides: object) -> dict:
    routine = {
        "wake": "07:00",
        "lights_out": "22:30",
        "eating_window": ["12:00", "21:00"],
        "every_day": [
            {"start": "22:30", "kind": "sleep", "title": "Lights out"},
            {"start": "07:00", "end": "07:05", "kind": "routine", "title": "Wake"},
        ],
        "days": {
            "monday": [
                {"start": "18:30", "end": "20:00", "kind": "training", "title": "BJJ"},
                {"start": "12:00", "kind": "meal", "title": "Meal 1"},
            ]
        },
    }
    routine.update(overrides)
    return routine


class TestBuildSchedulePayload:
    def test_merges_every_day_blocks_and_sorts_by_start(self) -> None:
        payload = build_schedule_payload(_config(_routine()), date(2026, 10, 19))
        monday = payload["days"][0]
        assert [b["title"] for b in monday["blocks"]] == ["Wake", "Meal 1", "BJJ", "Lights out"]

    def test_day_without_own_blocks_gets_every_day_blocks_only(self) -> None:
        payload = build_schedule_payload(_config(_routine()), date(2026, 10, 19))
        tuesday = payload["days"][1]
        assert [b["title"] for b in tuesday["blocks"]] == ["Wake", "Lights out"]

    def test_marks_today_by_weekday(self) -> None:
        payload = build_schedule_payload(_config(_routine()), date(2026, 10, 21))  # Wednesday
        assert payload["today"] == "wednesday"
        assert [d["day"] for d in payload["days"] if d["is_today"]] == ["wednesday"]

    def test_day_eating_window_override(self) -> None:
        routine = _routine(day_eating_window={"saturday": ["11:00", "21:00"]})
        payload = build_schedule_payload(_config(routine), date(2026, 10, 19))
        by_day = {d["day"]: d for d in payload["days"]}
        assert by_day["saturday"]["eating_window"] == ["11:00", "21:00"]
        assert by_day["sunday"]["eating_window"] == ["12:00", "21:00"]

    def test_does_not_mutate_config(self) -> None:
        routine = _routine()
        build_schedule_payload(_config(routine), date(2026, 10, 19))
        assert routine["every_day"][0]["title"] == "Lights out"


class TestStrengthWorkouts:
    def test_linked_block_gets_exercises_and_notes(self) -> None:
        routine = _routine(
            days={
                "monday": [
                    {
                        "start": "09:30",
                        "end": "10:40",
                        "kind": "training",
                        "strength_session": "strength_a",
                        "title": "Strength A",
                    }
                ]
            }
        )
        config = _config(routine)
        config["weekly_architecture"]["strength_sessions"] = {
            "strength_a": {"exercises": ["pull-ups: 4x5-8", "dips: 3x6-10"]},
            "notes": "Strength first,\n  yoga after.",
        }
        payload = build_schedule_payload(config, date(2026, 10, 19))
        block = next(b for b in payload["days"][0]["blocks"] if b["title"] == "Strength A")
        assert block["exercises"] == ["pull-ups: 4x5-8", "dips: 3x6-10"]
        assert block["workout_notes"] == "Strength first, yoga after."

    def test_unlinked_blocks_get_no_workout(self) -> None:
        payload = build_schedule_payload(_config(_routine()), date(2026, 10, 19))
        assert all("exercises" not in b for b in payload["days"][0]["blocks"])

    def test_unknown_link_flagged(self) -> None:
        routine = _routine(
            days={
                "monday": [
                    {
                        "start": "09:30",
                        "kind": "training",
                        "strength_session": "strength_z",
                        "title": "X",
                    }
                ]
            }
        )
        assert validate_routine(routine, {"strength_a": {}}) == [
            "monday: 'X' links unknown session 'strength_z'"
        ]

    def test_real_monday_and_wednesday_show_their_workouts(self) -> None:
        config = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
        payload = build_schedule_payload(config, date(2026, 10, 19))
        by_day = {d["day"]: d for d in payload["days"]}
        for day in ("monday", "wednesday"):
            strength = [b for b in by_day[day]["blocks"] if b.get("strength_session")]
            assert len(strength) == 1 and strength[0]["exercises"], day


class TestValidateRoutine:
    def test_clean_routine_has_no_problems(self) -> None:
        assert validate_routine(_routine()) == []

    def test_meal_outside_window_flagged(self) -> None:
        brekkie = {"start": "09:00", "kind": "meal", "title": "Brekkie"}
        routine = _routine(days={"monday": [brekkie]})
        assert validate_routine(routine) == [
            "monday: meal 'Brekkie' at 09:00 is outside the window"
        ]

    def test_overlap_flagged(self) -> None:
        routine = _routine(
            days={
                "monday": [
                    {"start": "09:00", "end": "10:00", "kind": "training", "title": "A"},
                    {"start": "09:30", "end": "10:30", "kind": "training", "title": "B"},
                ]
            }
        )
        assert validate_routine(routine) == ["monday: 'A' overlaps 'B'"]

    def test_end_before_start_flagged(self) -> None:
        routine = _routine(
            days={"monday": [{"start": "10:00", "end": "09:00", "kind": "rest", "title": "X"}]}
        )
        assert "monday: 'X' ends before it starts" in validate_routine(routine)


class TestRealConfig:
    def test_real_routine_is_consistent(self) -> None:
        config = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
        plan = config["weekly_architecture"]
        assert validate_routine(plan["daily_routine"], plan["strength_sessions"]) == []

    def test_real_routine_covers_all_days_with_morning_routine(self) -> None:
        config = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
        payload = build_schedule_payload(config, date(2026, 10, 19))
        assert [d["day"] for d in payload["days"]] == list(WEEKDAYS)
        for day in payload["days"]:
            kinds = {b["kind"] for b in day["blocks"]}
            assert {"mind", "mobility", "sleep"} <= kinds, day["day"]

    def test_no_bjj_on_tuesday(self) -> None:
        config = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
        tuesday = next(
            d for d in config["weekly_architecture"]["weekly_template"] if d["day"] == "tuesday"
        )
        assert all(s["type"] != "bjj" for s in tuesday["sessions"])


def test_schedule_route() -> None:
    response = TestClient(app).get("/api/schedule")
    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 7
    assert sum(d["is_today"] for d in body["days"]) == 1
