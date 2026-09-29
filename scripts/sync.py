#!/usr/bin/env python3
"""Daily live sync entrypoint (kickoff doc Phase 6).

    uv run python scripts/sync.py                 # trailing 3 days
    uv run python scripts/sync.py --days 7

Covers Garmin (activities + daily wellness + per-lap detail for BJJ
activities), Health Auto Export (weight, lean body mass, BMI), and RENPHO's
own CSV export (full body-composition detail — see `ingest/renpho_csv.py`).
Live Strava sync is deliberately skipped: Strava introduced a paid
($11.99/mo) developer API tier in June 2026, and Garmin already covers
current activities — Strava's role in this project is purely historical
backfill (already done, see `scripts/backfill.py`).

Health Auto Export (the iOS app, Premium tier) folder-drops JSON files into
`HEALTH_AUTO_EXPORT_DIR` on its own schedule -- **must be set in `.env` to the
app's actual live iCloud Drive folder** (find it with `mdfind -name
"<automation name>"`, never guessable/assumable), not left on the
`data/raw/health_auto_export` default, which is just a one-time manual test
copy from 2026-08-28 that nothing refreshes. Real bug found 2026-08-29: this
was left unset for over a week with zero errors, silently serving stale
weight the whole time — see CLAUDE.md's "Real bug found: weight had been
silently stale" for the full story. This is a genuinely different JSON
schema from the native Health app's `export.xml`
(`ingest/apple_health.py`/`scripts/backfill.py --source apple_health`), not a
re-run of that same path (an earlier draft of this docstring assumed it would
be; corrected once the real export was inspected — see
`ingest/health_auto_export.py`'s module docstring). Only `weight_body_mass`
is extracted, same allowlist-by-source-name policy as the bulk XML ingester.

Fetches a trailing window (default 3 days) rather than "since last sync",
deliberately: Garmin sometimes revises a day's wellness numbers after the
fact (a delayed HRV computation, a firmware backfill), so re-upserting a
short trailing window on every run self-heals those revisions for free.
Idempotent either way (`db.upsert()` on natural keys) — running this twice in
a row for the same window is always safe.

The actual sync/dedup logic lives in `health_os.ingest.live_sync` (extracted
2026-09-17) — this script is now a thin CLI wrapper (argparse + exit code)
so the exact same implementation also backs `api/sync.py`'s "sync now"
button on the frontend, rather than two independently-driftable copies.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from health_os.core import db  # noqa: E402
from health_os.ingest.live_sync import DEFAULT_WINDOW_DAYS, run_live_sync  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"trailing window size in days, inclusive of today (default {DEFAULT_WINDOW_DAYS})",
    )
    parser.add_argument("--db-path", default=None, help="Override HEALTH_OS_DB_PATH")
    args = parser.parse_args(argv)

    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    conn = db.init_db(args.db_path)
    try:
        result = run_live_sync(conn, config, days=args.days)
    finally:
        conn.close()

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
