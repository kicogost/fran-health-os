#!/usr/bin/env python3
"""Log the daily subjective_log entry: Hooper-Mackinnon-inspired wellness
questionnaire plus the original free-text/boolean fields.

    uv run python scripts/log_wellness.py
    uv run python scripts/log_wellness.py --sleep-quality 3 --stress 2 --fatigue 4 --soreness 5

All four wellness scores are 1 (best) to 10 (worst) — same polarity throughout,
so `hooper_index` (their sum, computed automatically) is always "lower is
better," 4 to 40. Upserts on date: logging today twice updates it rather than
duplicating. Every field is optional — log just the wellness scores some days,
just protein/social-meal on others, whatever's actually true that day.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.core.models import SubjectiveLogEntry, merge_subjective_log_entry  # noqa: E402

_WELLNESS_LABELS = {
    "sleep_quality": "Sleep quality",
    "stress": "Stress",
    "fatigue": "Fatigue",
    "muscle_soreness": "Muscle soreness",
}


def _today_madrid() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()


def _prompt(label: str, default: str | None = None, *, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        if not raw and not required:
            return ""
        if raw:
            return raw
        print("  required.")


def _prompt_int_optional(label: str, *, lo: int, hi: int) -> int | None:
    while True:
        raw = _prompt(f"{label} ({lo}-{hi}, blank to skip)", required=False)
        if not raw:
            return None
        try:
            val = int(raw)
        except ValueError:
            print("  must be a whole number.")
            continue
        if not lo <= val <= hi:
            print(f"  must be between {lo} and {hi}.")
            continue
        return val


def _prompt_bool_optional(label: str) -> bool | None:
    raw = _prompt(f"{label} (y/n, blank to skip)", required=False).lower()
    if not raw:
        return None
    return raw.startswith("y")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--sleep-quality", type=int, default=None, help="1 (best) - 10 (worst)")
    parser.add_argument("--stress", type=int, default=None, help="1 (best) - 10 (worst)")
    parser.add_argument("--fatigue", type=int, default=None, help="1 (best) - 10 (worst)")
    parser.add_argument(
        "--soreness", dest="muscle_soreness", type=int, default=None, help="1 (best) - 10 (worst)"
    )
    parser.add_argument("--protein-hit", dest="protein_hit", action="store_true", default=None)
    parser.add_argument("--no-protein-hit", dest="protein_hit", action="store_false")
    parser.add_argument("--gassed", action="store_true", default=None)
    parser.add_argument("--not-gassed", dest="gassed", action="store_false")
    parser.add_argument("--social-meal", dest="social_meal", action="store_true", default=None)
    parser.add_argument("--no-social-meal", dest="social_meal", action="store_false")
    parser.add_argument("--felt-note", dest="felt_note", default=None)
    parser.add_argument("--niggles", default=None)
    parser.add_argument("--day-note", dest="day_note", default=None)
    parser.add_argument("--db-path", default=None)
    return parser


def _any_flag_set(args: argparse.Namespace) -> bool:
    fields = (
        "sleep_quality",
        "stress",
        "fatigue",
        "muscle_soreness",
        "protein_hit",
        "gassed",
        "social_meal",
        "felt_note",
        "niggles",
        "day_note",
    )
    return any(getattr(args, f) is not None for f in fields)


def resolve_entry(args: argparse.Namespace) -> SubjectiveLogEntry:
    """Flag mode if any content flag was passed, interactive otherwise — unlike
    log_bjj.py this isn't all-or-nothing, since every field here is genuinely
    optional day to day (some days it's just the wellness scores, some days
    just a social-meal flag).
    """
    date = args.date or _today_madrid()

    if _any_flag_set(args):
        return SubjectiveLogEntry(
            date=date,
            felt_note=args.felt_note,
            protein_hit=args.protein_hit,
            gassed=args.gassed,
            niggles=args.niggles,
            day_note=args.day_note,
            social_meal=args.social_meal,
            sleep_quality=args.sleep_quality,
            stress=args.stress,
            fatigue=args.fatigue,
            muscle_soreness=args.muscle_soreness,
        )

    date = _prompt("Date (YYYY-MM-DD)", date)
    print("Wellness (1 = best, 10 = worst; blank to skip any):")
    sleep_quality = _prompt_int_optional(f"  {_WELLNESS_LABELS['sleep_quality']}", lo=1, hi=10)
    stress = _prompt_int_optional(f"  {_WELLNESS_LABELS['stress']}", lo=1, hi=10)
    fatigue = _prompt_int_optional(f"  {_WELLNESS_LABELS['fatigue']}", lo=1, hi=10)
    muscle_soreness = _prompt_int_optional(f"  {_WELLNESS_LABELS['muscle_soreness']}", lo=1, hi=10)
    protein_hit = _prompt_bool_optional("Hit 180g protein yesterday")
    social_meal = _prompt_bool_optional("Social meal yesterday")
    niggles = _prompt("Niggles (free text)", required=False) or None
    day_note = _prompt("Day note", required=False) or None

    return SubjectiveLogEntry(
        date=date,
        protein_hit=protein_hit,
        niggles=niggles,
        day_note=day_note,
        social_meal=social_meal,
        sleep_quality=sleep_quality,
        stress=stress,
        fatigue=fatigue,
        muscle_soreness=muscle_soreness,
    )


def _warn_if_overwriting(conn: sqlite3.Connection, entry: SubjectiveLogEntry) -> None:
    existing = conn.execute(
        "SELECT hooper_index FROM subjective_log WHERE date = ?", (entry.date,)
    ).fetchone()
    if existing is not None:
        prior = existing["hooper_index"]
        print(f"Updating existing entry for {entry.date} (was hooper_index={prior})")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        entry = resolve_entry(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    conn = db.init_db(args.db_path)
    try:
        _warn_if_overwriting(conn, entry)
        # Merge with any existing row for this date FIRST -- hooper_index can
        # only be computed once all 4 sub-scores are known, which may have
        # been logged across separate calls (see merge_subjective_log_entry's
        # docstring for the real bug this fixes).
        entry = merge_subjective_log_entry(conn, entry)
        db.upsert(conn, "subjective_log", entry.to_row(), ["date"])
    finally:
        conn.close()

    print(f"Logged: {entry.date}", end="")
    if entry.hooper_index is not None:
        print(f", hooper_index={entry.hooper_index} (4=excellent, 40=terrible)")
    else:
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
