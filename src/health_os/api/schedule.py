"""Schedule page -- Francisco's strict weekly routine with clock times
(wake-up, meditation, mobility, meals, coffee, training, wind-down, lights
out), read straight from `config/athlete.yaml: weekly_architecture.
daily_routine`. Pure config assembly, no database: the routine is the plan,
not a measurement.

Each day's timeline is the `every_day` blocks merged with that day's own
blocks, sorted by start time. A block outside the day's eating window
(`day_eating_window` overrides `eating_window`) that is a meal is a config
mistake, caught by `validate_routine()` and covered by a test against the
real config.
"""

from __future__ import annotations

from datetime import date
from typing import Any

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _day_blocks(routine: dict[str, Any], day: str) -> list[dict[str, Any]]:
    blocks = [dict(b) for b in routine.get("every_day", [])]
    blocks += [dict(b) for b in (routine.get("days") or {}).get(day, [])]
    blocks.sort(key=lambda b: (_minutes(b["start"]), b.get("end") or b["start"]))
    return blocks


def _eating_window(routine: dict[str, Any], day: str) -> list[str]:
    overrides = routine.get("day_eating_window") or {}
    return list(overrides.get(day, routine["eating_window"]))


def validate_routine(routine: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems; empty means consistent.

    Checks: end after start, timed blocks on the same day don't overlap, and
    every meal falls inside that day's eating window.
    """
    problems: list[str] = []
    for day in WEEKDAYS:
        blocks = _day_blocks(routine, day)
        window_start, window_end = (_minutes(t) for t in _eating_window(routine, day))
        timed = []
        for b in blocks:
            start = _minutes(b["start"])
            if b.get("end"):
                end = _minutes(b["end"])
                if end <= start:
                    problems.append(f"{day}: '{b['title']}' ends before it starts")
                timed.append((start, end, b["title"]))
            if b["kind"] == "meal" and not window_start <= start <= window_end:
                problems.append(f"{day}: meal '{b['title']}' at {b['start']} is outside the window")
        timed.sort()
        for (_, end_a, title_a), (start_b, _, title_b) in zip(timed, timed[1:], strict=False):
            if start_b < end_a:
                problems.append(f"{day}: '{title_a}' overlaps '{title_b}'")
    return problems


def build_schedule_payload(config: dict[str, Any], today: date) -> dict[str, Any]:
    plan = config["weekly_architecture"]
    routine = plan["daily_routine"]
    today_name = WEEKDAYS[today.weekday()]
    days = [
        {
            "day": day,
            "is_today": day == today_name,
            "eating_window": _eating_window(routine, day),
            "blocks": _day_blocks(routine, day),
        }
        for day in WEEKDAYS
    ]
    return {
        "today": today_name,
        "starts": plan.get("starts"),
        "wake": routine["wake"],
        "lights_out": routine["lights_out"],
        "eating_window": list(routine["eating_window"]),
        "days": days,
    }
