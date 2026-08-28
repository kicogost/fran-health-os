#!/usr/bin/env python3
"""Print the weekly retro (kickoff doc Phase 7): 7-day weight trend, sessions
completed vs. planned, total load/TSB/monotony, sleep, protein adherence,
social-meal count, waist delta.

    uv run python scripts/weekly_retro.py                        # week ending today
    uv run python scripts/weekly_retro.py --week-ending 2026-08-24

Meant for Sundays (the kickoff doc's own cadence) but works for any date —
`--week-ending` doesn't have to be a Sunday, it's just "the trailing 7 days
ending on this date."
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from health_os.coach.weekly_retro import compute_weekly_retro, format_weekly_retro  # noqa: E402
from health_os.core import db  # noqa: E402
from health_os.core.timezones import to_local_date  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"


def _today_local() -> str:
    return to_local_date(datetime.now(UTC))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--week-ending", default=None, help="YYYY-MM-DD, default today (Europe/Madrid)"
    )
    parser.add_argument("--db-path", default=None, help="Override HEALTH_OS_DB_PATH")
    args = parser.parse_args(argv)

    week_ending = args.week_ending or _today_local()
    try:
        date.fromisoformat(week_ending)
    except ValueError:
        print(f"Error: '{week_ending}' isn't a valid YYYY-MM-DD date.")
        return 1

    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    conn = db.init_db(args.db_path)
    try:
        plan = compute_weekly_retro(conn, config, week_ending)
        print(format_weekly_retro(plan))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
