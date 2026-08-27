#!/usr/bin/env python3
"""Log a BJJ session — the manual, first-class ingestion path (kickoff doc 2.4).

Interactive (prompts for every field):

    uv run python scripts/log_bjj.py

Or pass flags directly for a quick one-liner after class:

    uv run python scripts/log_bjj.py --type class --duration 90 --rpe 7 \\
        --rounds-rolled 6 --rounds-gassed 1 --feeling tired --niggles "left knee tight"

Upserts on (date, session_type) — logging the same type twice for the same date
updates the existing row rather than creating a duplicate (warns before doing so).
`computed_load` is Foster's method (duration_min x session_rpe), computed
automatically by `core.models.BjjSession` — never entered by hand.

`rounds_rolled`/`rounds_gassed`/`feeling` are only asked for `class` and
`open_mat` sessions — `gi_drilling` is technique-only (config/athlete.yaml), so
there's nothing to roll and asking would just train you to enter zeros.
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
from health_os.core.models import SESSION_FEELINGS, BjjSession  # noqa: E402

SESSION_TYPES = ("class", "open_mat", "gi_drilling")
ROLLING_SESSION_TYPES = ("class", "open_mat")


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


def _prompt_choice(label: str, choices: tuple[str, ...], default: str | None = None) -> str:
    while True:
        val = _prompt(f"{label} ({'/'.join(choices)})", default)
        if val in choices:
            return val
        print(f"  must be one of: {', '.join(choices)}")


def _prompt_int(label: str, *, lo: int, hi: int) -> int:
    while True:
        raw = _prompt(f"{label} ({lo}-{hi})")
        try:
            val = int(raw)
        except ValueError:
            print("  must be a whole number.")
            continue
        if not lo <= val <= hi:
            print(f"  must be between {lo} and {hi}.")
            continue
        return val


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--type", dest="session_type", choices=SESSION_TYPES)
    parser.add_argument("--duration", type=int, help="minutes")
    parser.add_argument("--rpe", type=int, help="session RPE, 1-10")
    parser.add_argument("--rounds-rolled", type=int, default=None)
    parser.add_argument(
        "--rounds-gassed", type=int, default=None, help="how many of those you got gassed on"
    )
    parser.add_argument("--feeling", dest="session_feeling", choices=SESSION_FEELINGS, default=None)
    parser.add_argument("--niggles", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--db-path", default=None)
    return parser


def resolve_session(args: argparse.Namespace) -> BjjSession:
    """Build the session either from flags, or — if none of the three required
    fields were passed at all — interactively. Deliberately all-or-nothing: a
    partial flag set (e.g. just --type) is treated as flag mode and fails fast
    asking for the rest, rather than silently prompting for only what's missing.
    """
    interactive = args.session_type is None and args.duration is None and args.rpe is None

    if interactive:
        date = _prompt("Date (YYYY-MM-DD)", args.date or _today_madrid())
        session_type = _prompt_choice("Session type", SESSION_TYPES, "class")
        duration_min = _prompt_int("Duration (min)", lo=1, hi=600)
        session_rpe = _prompt_int("Session RPE", lo=1, hi=10)
        if session_type in ROLLING_SESSION_TYPES:
            rounds_rolled = _prompt_int("Rounds rolled", lo=0, hi=30)
            rounds_gassed = _prompt_int("Rounds gassed on", lo=0, hi=rounds_rolled)
            session_feeling = _prompt_choice("Feeling at the end", SESSION_FEELINGS, "tired")
        else:
            rounds_rolled = rounds_gassed = session_feeling = None
        niggles = _prompt("Niggles (free text)", required=False) or None
        notes = _prompt("Notes", required=False) or None
    else:
        missing = [
            flag
            for flag, val in (
                ("--type", args.session_type),
                ("--duration", args.duration),
                ("--rpe", args.rpe),
            )
            if val is None
        ]
        if missing:
            raise SystemExit(
                f"Missing {', '.join(missing)}. Pass all three (--type, --duration, --rpe) "
                "for a flag-driven log, or omit all three for interactive prompts."
            )
        date = args.date or _today_madrid()
        session_type = args.session_type
        duration_min = args.duration
        session_rpe = args.rpe
        rounds_rolled = args.rounds_rolled
        rounds_gassed = args.rounds_gassed
        session_feeling = args.session_feeling
        niggles = args.niggles
        notes = args.notes

    return BjjSession(
        date=date,
        session_type=session_type,
        duration_min=duration_min,
        session_rpe=session_rpe,
        rounds_rolled=rounds_rolled,
        rounds_gassed=rounds_gassed,
        session_feeling=session_feeling,
        niggles=niggles,
        notes=notes,
    )


def _warn_if_overwriting(conn: sqlite3.Connection, session: BjjSession) -> None:
    existing = conn.execute(
        "SELECT duration_min, session_rpe, computed_load FROM bjj_sessions "
        "WHERE date = ? AND session_type = ?",
        (session.date, session.session_type),
    ).fetchone()
    if existing is not None:
        print(
            f"Updating existing {session.session_type} session on {session.date} "
            f"(was: {existing['duration_min']}min @ RPE {existing['session_rpe']}, "
            f"load {existing['computed_load']:.0f})"
        )


def _print_summary(session: BjjSession) -> None:
    parts = [
        f"Logged: {session.date} {session.session_type} — {session.duration_min}min "
        f"@ RPE {session.session_rpe} -> load {session.computed_load:.0f}"
    ]
    if session.rounds_rolled is not None:
        rounds_desc = f"{session.rounds_rolled} rounds"
        if session.rounds_gassed:
            rounds_desc += f" ({session.rounds_gassed} gassed)"
        parts.append(rounds_desc)
    if session.session_feeling:
        parts.append(f"felt {session.session_feeling}")
    print(", ".join(parts))
    if session.session_feeling == "dizzy":
        print(
            "  logged 'dizzy' — that's more than normal hard-training fatigue, keep an eye on it."
        )
    if session.niggles:
        print(f"  niggles: {session.niggles}")
    if session.notes:
        print(f"  notes: {session.notes}")


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
        db.upsert(conn, "bjj_sessions", session.to_row(), ["date", "session_type"])
    finally:
        conn.close()

    _print_summary(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
