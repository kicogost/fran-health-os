#!/usr/bin/env python3
"""Log a calisthenics session (migration 0003) — the exercise-level detail
Garmin's activity summary can't capture (record the session itself on the
watch as "Strength Training" for automatic duration/HR/calories, this covers
sets/reps/added weight per exercise for real progression tracking).

Interactive (walks through each exercise config/athlete.yaml prescribes for
the session type, prompting for what you actually did):

    uv run python scripts/log_calisthenics.py

Or a quick flag-mode one-liner covering just the overall session (no
per-exercise detail — use interactive mode for that):

    uv run python scripts/log_calisthenics.py --type strength_a --rpe 6

Upserts on (date, session_type) — logging the same type twice for the same
date updates it rather than creating a duplicate (warns before doing so).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.core.models import CalisthenicsSession  # noqa: E402

SESSION_TYPES = ("strength_a", "strength_b")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"


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


def _prompt_float_optional(label: str) -> float | None:
    raw = _prompt(f"{label} (blank to skip)", required=False)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print("  not a number, skipping.")
        return None


def _exercise_name(raw: str) -> str:
    """Config entries are full prescriptions, e.g. "weighted or slow-tempo
    pull-ups: 4x5 (superset with next)" -- just the name before the colon,
    for a clean prompt label.
    """
    return raw.split(":")[0].strip()


def _load_prescribed_exercises(session_type: str) -> list[str]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    sessions = config["comp_prep"]["strength_sessions"]
    return sessions.get(session_type, {}).get("exercises", [])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--type", dest="session_type", choices=SESSION_TYPES)
    parser.add_argument("--rpe", dest="session_rpe", type=int, default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--db-path", default=None)
    return parser


def resolve_session(args: argparse.Namespace) -> CalisthenicsSession:
    """Flag mode (session-level only, --type + at least one of --rpe/--notes)
    or full interactive mode walking every prescribed exercise -- mirrors
    log_bjj.py's all-or-nothing split for which mode you're in.
    """
    interactive = args.session_type is None

    if interactive:
        date = _prompt("Date (YYYY-MM-DD)", args.date or _today_madrid())
        session_type = _prompt_choice_calisthenics()
        exercises = []
        prescribed = _load_prescribed_exercises(session_type)
        if prescribed:
            print(f"Logging {len(prescribed)} exercises (blank sets to skip detail on one):")
            for raw in prescribed:
                name = _exercise_name(raw)
                print(f"  {raw}")
                sets = _prompt_int_optional(f"    {name} — sets", lo=1, hi=20)
                if sets is None:
                    continue
                reps = _prompt_int_optional("    reps", lo=1, hi=100)
                added_weight_kg = _prompt_float_optional("    added weight (kg)")
                ex_notes = _prompt("    notes", required=False) or None
                exercises.append(
                    {
                        "exercise": name,
                        "sets": sets,
                        "reps": reps,
                        "added_weight_kg": added_weight_kg,
                        "notes": ex_notes,
                    }
                )
        exercises.extend(_prompt_custom_exercises())
        session_rpe = _prompt_int_optional("Session RPE", lo=1, hi=10)
        notes = _prompt("Session notes", required=False) or None
    else:
        date = args.date or _today_madrid()
        session_type = args.session_type
        exercises = []
        session_rpe = args.session_rpe
        notes = args.notes

    return CalisthenicsSession(
        date=date,
        session_type=session_type,
        session_rpe=session_rpe,
        exercises=exercises or None,
        notes=notes,
    )


def _prompt_custom_exercises() -> list[dict]:
    """Beyond the prescribed list -- real gap found 2026-08-28 (Francisco's
    holiday-week substitution, e.g. push-ups/abs instead of the comp-prep
    exercises): `CalisthenicsSession.exercises` was always fully flexible at
    the model layer (no exercise-name validation in `__post_init__`), but
    this interactive loop only ever walked the prescribed list, so there was
    no way to actually log a substituted exercise with real sets/reps
    outside the free-text `notes` field. Keeps prompting for one more name
    until a blank entry ends it -- zero or many custom exercises, same as
    the prescribed loop's "blank sets to skip" pattern.
    """
    exercises: list[dict] = []
    print("Add any other exercise not in the list above (blank name to finish):")
    while True:
        name = _prompt("  Exercise name", required=False)
        if not name:
            return exercises
        sets = _prompt_int_optional(f"    {name} — sets", lo=1, hi=20)
        if sets is None:
            print("  skipped (no sets entered).")
            continue
        reps = _prompt_int_optional("    reps", lo=1, hi=100)
        added_weight_kg = _prompt_float_optional("    added weight (kg)")
        ex_notes = _prompt("    notes", required=False) or None
        exercises.append(
            {
                "exercise": name,
                "sets": sets,
                "reps": reps,
                "added_weight_kg": added_weight_kg,
                "notes": ex_notes,
            }
        )


def _prompt_choice_calisthenics() -> str:
    while True:
        val = _prompt(f"Session type ({'/'.join(SESSION_TYPES)})", "strength_a")
        if val in SESSION_TYPES:
            return val
        print(f"  must be one of: {', '.join(SESSION_TYPES)}")


def _warn_if_overwriting(conn: sqlite3.Connection, session: CalisthenicsSession) -> None:
    existing = conn.execute(
        "SELECT session_rpe FROM calisthenics_sessions WHERE date = ? AND session_type = ?",
        (session.date, session.session_type),
    ).fetchone()
    if existing is not None:
        print(f"Updating existing {session.session_type} session on {session.date}")


def _print_summary(session: CalisthenicsSession) -> None:
    parts = [f"Logged: {session.date} {session.session_type}"]
    if session.exercises:
        parts.append(f"{len(session.exercises)} exercises logged")
    if session.session_rpe is not None:
        parts.append(f"RPE {session.session_rpe}")
    print(", ".join(parts))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        session = resolve_session(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    conn = db.init_db(args.db_path)
    try:
        _warn_if_overwriting(conn, session)
        db.upsert(conn, "calisthenics_sessions", session.to_row(), ["date", "session_type"])
    finally:
        conn.close()

    _print_summary(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
