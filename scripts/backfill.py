#!/usr/bin/env python3
"""One-time historical backfill from the bulk export archives (kickoff doc Phase 2).

    uv run python scripts/backfill.py                    # all sources
    uv run python scripts/backfill.py --source strava     # one source

Looks for each source's export under `data/raw/<source>/`, either directly or one
level down in a single named subdirectory (matches how the real exports land —
e.g. `data/raw/strava/strava_export/activities.csv`). Every run is idempotent
(`db.upsert()` on natural keys) and logged to `ingest_runs`, so re-running this
against the same files is always safe and produces the same result.

Garmin's bulk-export parser isn't built yet — Francisco's Garmin export hadn't
arrived as of 2026-08-27 (it takes the platform days to generate). `--source
garmin` / `--source all` will say so rather than fail confusingly.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.ingest import apple_health, strava_bulk  # noqa: E402

DATA_RAW = Path("data/raw")


def _find_export_dir(base_dir: Path, marker_filename: str) -> Path | None:
    """`marker_filename` directly in `base_dir`, or one level down in a single
    named subdirectory — matches how the real exports actually land.
    """
    base_dir = Path(base_dir)
    if (base_dir / marker_filename).exists():
        return base_dir
    if base_dir.is_dir():
        for child in sorted(base_dir.iterdir()):
            if child.is_dir() and (child / marker_filename).exists():
                return child
    return None


def backfill_strava(conn: sqlite3.Connection, base_dir: Path = DATA_RAW / "strava") -> bool:
    export_dir = _find_export_dir(base_dir, "activities.csv")
    if export_dir is None:
        print(f"strava: no export found under {base_dir} (looking for activities.csv) — skipping")
        return True

    run_id = db.start_ingest_run(conn, "strava")
    rows_in = rows_upserted = 0
    try:
        for activity in strava_bulk.parse_activities_csv(export_dir):
            rows_in += 1
            db.upsert(conn, "activities", activity.to_row(), ["source", "source_id"])
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
        print(f"strava: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    db.finish_ingest_run(
        conn, run_id, status="success", rows_in=rows_in, rows_upserted=rows_upserted, rows_skipped=0
    )
    print(f"strava: {rows_upserted} activities upserted from {export_dir}")
    return True


def backfill_apple_health(
    conn: sqlite3.Connection, base_dir: Path = DATA_RAW / "apple_health"
) -> bool:
    export_dir = _find_export_dir(base_dir, "export.xml")
    if export_dir is None:
        print(f"apple_health: no export found under {base_dir} (looking for export.xml) — skipping")
        return True

    run_id = db.start_ingest_run(conn, "apple_health")
    rows_in = rows_upserted = 0
    try:
        config = apple_health.AppleHealthSourceConfig.from_yaml()
        for activity in apple_health.parse_workouts(export_dir, config):
            rows_in += 1
            db.upsert(conn, "activities", activity.to_row(), ["source", "source_id"])
            rows_upserted += 1
        for metric in apple_health.parse_daily_weight(export_dir, config):
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
        print(f"apple_health: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    db.finish_ingest_run(
        conn, run_id, status="success", rows_in=rows_in, rows_upserted=rows_upserted, rows_skipped=0
    )
    print(f"apple_health: {rows_upserted} rows upserted from {export_dir}")
    return True


def backfill_garmin(
    conn: sqlite3.Connection, base_dir: Path = DATA_RAW / "garmin" / "bulk_export"
) -> bool:
    base_dir = Path(base_dir)
    if not base_dir.exists() or not any(base_dir.iterdir()):
        print(f"garmin: no export under {base_dir} yet (takes days to generate) — skipping")
        return True
    print(
        f"garmin: files found under {base_dir}, but ingest/garmin_bulk.py isn't written yet — "
        "inspect the real structure before writing it (see CLAUDE.md Phase 2 status). Skipping."
    )
    return True


_BACKFILLERS = {
    "strava": backfill_strava,
    "apple_health": backfill_apple_health,
    "garmin": backfill_garmin,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=[*_BACKFILLERS, "all"], default="all")
    parser.add_argument("--db-path", default=None, help="Override HEALTH_OS_DB_PATH")
    args = parser.parse_args(argv)

    sources = list(_BACKFILLERS) if args.source == "all" else [args.source]
    conn = db.init_db(args.db_path)
    try:
        results = {source: _BACKFILLERS[source](conn) for source in sources}
    finally:
        conn.close()

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
