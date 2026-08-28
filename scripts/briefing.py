#!/usr/bin/env python3
"""Print today's coaching briefing (kickoff doc Phase 7).

    uv run python scripts/briefing.py
    uv run python scripts/briefing.py --date 2026-08-24   # any past date

Reads from whatever's already in `data/health.db` — run `scripts/sync.py`
first if you want today's numbers reflected. This is deliberately a separate
command, not auto-chained into sync.py: every script in this project does one
thing (see `scripts/backfill.py`, `sync.py`, `log_bjj.py`, ...). The "one
command each morning" flow from the kickoff doc's definition-of-done is

    uv run python scripts/sync.py && uv run python scripts/briefing.py

composing the two into a single command is a Phase 8 (scheduling) concern,
not duplicated here.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from health_os.coach.briefing import build_briefing  # noqa: E402
from health_os.core import db  # noqa: E402
from health_os.core.timezones import to_local_date  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"


def _today_local() -> str:
    return to_local_date(datetime.now(UTC))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--db-path", default=None, help="Override HEALTH_OS_DB_PATH")
    args = parser.parse_args(argv)

    today = args.date or _today_local()
    try:
        date.fromisoformat(today)  # fail fast, friendly, on a malformed --date
    except ValueError:
        print(f"Error: '{today}' isn't a valid YYYY-MM-DD date.")
        return 1

    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    conn = db.init_db(args.db_path)
    try:
        print(build_briefing(conn, config, today))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
