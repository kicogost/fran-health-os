#!/usr/bin/env python3
"""Daily live sync entrypoint (kickoff doc Phase 6).

    uv run python scripts/sync.py                 # trailing 3 days
    uv run python scripts/sync.py --days 7

Covers Garmin (activities + daily wellness + per-lap detail for BJJ
activities) and Health Auto Export (weight only). Live Strava sync is
deliberately skipped: Strava introduced a paid
($11.99/mo) developer API tier in June 2026, and Garmin already covers
current activities — Strava's role in this project is purely historical
backfill (already done, see `scripts/backfill.py`).

Health Auto Export (the iOS app, Premium tier) folder-drops JSON files into
`HEALTH_AUTO_EXPORT_DIR` (default `data/raw/health_auto_export`, synced there
from iCloud Drive) on its own schedule — this is a genuinely different JSON
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
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from garminconnect import GarminConnectAuthenticationError  # noqa: E402

from health_os.core import db  # noqa: E402
from health_os.core.dedupe import dedupe_activities  # noqa: E402
from health_os.core.timezones import to_local_date  # noqa: E402
from health_os.ingest import garmin, health_auto_export  # noqa: E402

DEFAULT_WINDOW_DAYS = 3
DEFAULT_HEALTH_AUTO_EXPORT_DIR = "data/raw/health_auto_export"


def _today_local() -> date:
    """Europe/Madrid's current calendar date, not the sync machine's system
    tz (design principle 7 — never assume system tz == Europe/Madrid)."""
    return date.fromisoformat(to_local_date(datetime.now(UTC)))


def sync_garmin(conn: sqlite3.Connection, start_date: date, end_date: date) -> bool:
    run_id = db.start_ingest_run(conn, "garmin_live")
    rows_in = rows_upserted = 0
    errors: list[str] = []

    try:
        client = garmin.build_and_login_client()
    except GarminConnectAuthenticationError as exc:
        db.finish_ingest_run(conn, run_id, status="failed", errors=[str(exc)])
        print(
            "garmin: authentication failed — add GARMIN_EMAIL/GARMIN_PASSWORD to your "
            ".env (see .env.example), or they may need updating.\n"
            f"  ({exc})"
        )
        return False
    except Exception as exc:  # noqa: BLE001 - reported to ingest_runs, not swallowed
        db.finish_ingest_run(conn, run_id, status="failed", errors=[str(exc)])
        print(f"garmin: FAILED to log in — {exc}")
        traceback.print_exc()
        return False

    try:
        for metric in garmin.fetch_daily_metrics(client, start_date, end_date, errors=errors):
            rows_in += 1
            db.upsert(conn, "daily_metrics", metric.to_row(), ["date"])
            rows_upserted += 1

        for activity in garmin.fetch_activities(client, start_date, end_date, errors=errors):
            rows_in += 1
            db.upsert(conn, "activities", activity.to_row(), ["source", "source_id"])
            rows_upserted += 1
            # Spot-check print, not just a count: ingest/garmin.py's docstring
            # flags live activity duration/distance units (seconds/meters) as
            # an assumption not yet cross-validated against a real account —
            # these numbers should look obviously right (or wrong) at a
            # glance, same spirit as the elevationGain cross-check that caught
            # a real unit bug in garmin_bulk.py.
            print(
                f"  activity: {activity.local_date} {activity.sport or '?'} "
                f"{(activity.duration_s or 0) / 60:.0f}min "
                f"{(activity.distance_m or 0) / 1000:.2f}km"
            )

            # Lap detail is only fetched for BJJ activities (sub_sport=="bjj",
            # see docs/bjj_recording_workflow.md) -- most other sports either
            # have no meaningful laps (a single-lap run) or don't need
            # round-by-round detail, and fetching it for every activity would
            # be one extra API call per activity for no benefit.
            if activity.sub_sport == "bjj":
                lap_count = 0
                for lap in garmin.fetch_activity_laps(client, activity.source_id, errors=errors):
                    db.upsert(conn, "activity_laps", lap.to_row(), ["activity_id", "lap_index"])
                    lap_count += 1
                if lap_count:
                    print(f"    laps: {lap_count} lap(s) upserted")
    except Exception as exc:  # noqa: BLE001 - reported to ingest_runs, not swallowed
        errors.append(str(exc))
        db.finish_ingest_run(
            conn,
            run_id,
            status="failed",
            rows_in=rows_in,
            rows_upserted=rows_upserted,
            errors=errors,
        )
        print(f"garmin: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    # `errors` here are per-endpoint/per-activity validation warnings that
    # fetch_daily_metrics/fetch_activities already skipped past gracefully —
    # non-fatal, but recorded rather than silently dropped.
    db.finish_ingest_run(
        conn,
        run_id,
        status="success",
        rows_in=rows_in,
        rows_upserted=rows_upserted,
        errors=errors or None,
    )
    print(f"garmin: {rows_upserted} rows upserted for {start_date}..{end_date}")
    if errors:
        print(f"garmin: {len(errors)} non-fatal warning(s) — see ingest_runs.errors for detail")
    return True


def sync_health_auto_export(conn: sqlite3.Connection) -> bool:
    export_dir = Path(os.environ.get("HEALTH_AUTO_EXPORT_DIR", DEFAULT_HEALTH_AUTO_EXPORT_DIR))
    if not export_dir.exists() or not any(export_dir.glob("HealthAutoExport-*.json")):
        print(f"health_auto_export: no export found under {export_dir} yet — skipping")
        return True

    run_id = db.start_ingest_run(conn, "health_auto_export")
    rows_in = rows_upserted = 0
    try:
        for metric in health_auto_export.parse_weight(export_dir):
            rows_in += 1
            db.upsert(conn, "daily_metrics", metric.to_row(), ["date"])
            rows_upserted += 1
    except Exception as exc:  # noqa: BLE001 - reported to ingest_runs, not swallowed
        db.finish_ingest_run(
            conn,
            run_id,
            status="failed",
            rows_in=rows_in,
            rows_upserted=rows_upserted,
            errors=[str(exc)],
        )
        print(f"health_auto_export: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    db.finish_ingest_run(
        conn, run_id, status="success", rows_in=rows_in, rows_upserted=rows_upserted, rows_skipped=0
    )
    print(f"health_auto_export: {rows_upserted} rows upserted from {export_dir}")
    return True


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

    end_date = _today_local()
    start_date = end_date - timedelta(days=args.days - 1)

    conn = db.init_db(args.db_path)
    try:
        garmin_ok = sync_garmin(conn, start_date, end_date)
        health_auto_export_ok = sync_health_auto_export(conn)
        ok = garmin_ok and health_auto_export_ok

        # Cross-source dedup (design principle 5) always runs after ingestion,
        # regardless of per-source outcome — see scripts/backfill.py's
        # identical pattern and core/dedupe.py's module docstring for why.
        dedupe_result = dedupe_activities(conn)
        if dedupe_result.groups_merged:
            print(
                f"dedupe: merged {dedupe_result.groups_merged} duplicate group(s), "
                f"removed {dedupe_result.rows_deleted} row(s)"
            )
        else:
            print("dedupe: no duplicates found")
    finally:
        conn.close()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
