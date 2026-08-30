#!/usr/bin/env python3
"""Checks whether a date's Hooper-Mackinnon wellness fields (sleep_quality,
stress, fatigue, muscle_soreness) have all been logged.

Built 2026-08-30 for `scripts/quiet_sync.sh`'s evening reminder: Francisco
asked directly whether he needs to log wellness every day, and the honest
answer was yes, ideally — the deload trigger's `hooper_sustained_high()`
needs 3 *consecutive* days (a single gap resets the streak) and the
correlation engine needs 30 real paired days, so sporadic logging quietly
undermines both. Morning is the ideal time to actually log it (same-day
readiness score/briefing only reflects it if it's there before the morning
sync runs) — this check exists purely as an evening backstop for a day
that got missed, not to replace logging it in the morning.

Exit code 0 = fully logged, 1 = missing (any of the 4 fields null or no
row at all for that date). Prints one line either way, for the caller's
log file — deliberately not silent on success either, so
`data/logs/quiet_sync.log` shows what happened on both paths, not just
the reminder path.

    uv run python scripts/check_wellness_logged.py            # today, Europe/Madrid
    uv run python scripts/check_wellness_logged.py --date 2026-08-29
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402

_WELLNESS_COLUMNS = ("sleep_quality", "stress", "fatigue", "muscle_soreness")


def _today_madrid() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()


def is_wellness_logged(conn, date_str: str) -> bool:
    """True only if EVERY Hooper-Mackinnon field has a real value for
    `date_str` -- a partially-logged day (e.g. only sleep_quality set)
    still can't compute a real `hooper_index` (core.models.
    SubjectiveLogEntry only computes it when all four are present), so a
    partial day counts as "not logged" for this check too.
    """
    row = conn.execute(
        f"SELECT {', '.join(_WELLNESS_COLUMNS)} FROM subjective_log WHERE date = ?",  # noqa: S608
        (date_str,),
    ).fetchone()
    if row is None:
        return False
    return all(row[col] is not None for col in _WELLNESS_COLUMNS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--db-path", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    date_str = args.date or _today_madrid()

    conn = db.init_db(args.db_path)
    try:
        logged = is_wellness_logged(conn, date_str)
    finally:
        conn.close()

    if logged:
        print(f"wellness already logged for {date_str}")
        return 0
    print(f"wellness not fully logged for {date_str}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
