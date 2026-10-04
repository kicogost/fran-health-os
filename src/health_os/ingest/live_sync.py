"""Shared live-sync orchestration — Garmin (activities + daily wellness +
BJJ lap detail), Health Auto Export (weight/lean-mass/BMI), and RENPHO's own
CSV export (full body-composition detail), plus the cross-source dedup pass
that always runs after ingestion (design principle 5).

Extracted from `scripts/sync.py` (2026-09-17) so the exact same
implementation backs both the daily CLI/launchd entrypoint AND the
frontend's manual "sync now" button (`api/sync.py`) — one real
implementation, not two independently-driftable copies, the same
"assembled once, reused everywhere" discipline this project already applies
to `coach/briefing.py` and every `metrics/` module shared across the CLI
scripts and the API.
"""

from __future__ import annotations

import os
import sqlite3
import traceback
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from garminconnect import GarminConnectAuthenticationError

from health_os.core import db
from health_os.core.dedupe import DedupeResult, dedupe_activities
from health_os.core.timezones import to_local_date
from health_os.ingest import garmin, health_auto_export, renpho_csv
from health_os.metrics.bjj_laps import auto_detect_rounds

DEFAULT_WINDOW_DAYS = 3
DEFAULT_HEALTH_AUTO_EXPORT_DIR = "data/raw/health_auto_export"
DEFAULT_RENPHO_CSV_DIR = "data/raw/renpho"

# A lap shorter than this is an accidental button-tap, not a real
# round-by-round boundary -- see the real bug this fixed, 2026-10-02.
MIN_REAL_LAP_DURATION_S = 30.0


def today_local() -> date:
    """Europe/Madrid's current calendar date, not the sync machine's system
    tz (design principle 7 — never assume system tz == Europe/Madrid)."""
    return date.fromisoformat(to_local_date(datetime.now(UTC)))


def sync_garmin(
    conn: sqlite3.Connection, config: dict[str, Any], start_date: date, end_date: date
) -> bool:
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
            db.upsert(
                conn, "daily_metrics", metric.to_row(), ["date"], merge_json_columns=["sources"]
            )
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
                real_lap_count = 0
                for lap in garmin.fetch_activity_laps(client, activity.source_id, errors=errors):
                    db.upsert(conn, "activity_laps", lap.to_row(), ["activity_id", "lap_index"])
                    lap_count += 1
                    # A near-instantaneous "lap" (an accidental double-tap of
                    # the lap button, or a final split Garmin inserts when
                    # the recording stops) isn't real round-by-round
                    # lapping -- real bug found 2026-10-02: Francisco's
                    # 2026-09-28 AND 2026-10-02 sessions both had exactly
                    # this shape (one near-full-session lap + one ~1s final
                    # lap), which made `lap_count <= 1` below incorrectly
                    # treat them as "manually lapped" and skip
                    # auto-detection entirely, even though there was no real
                    # round-by-round ground truth to prefer. Still upserted
                    # above regardless (never discard real raw Garmin data)
                    # -- only excluded from this count.
                    if (lap.duration_s or 0) >= MIN_REAL_LAP_DURATION_S:
                        real_lap_count += 1
                if lap_count:
                    print(f"    laps: {lap_count} lap(s) upserted")

                # Auto-detect rounds from the raw HR stream ONLY when
                # Francisco didn't manually lap this session (2026-09-29 --
                # he doesn't want to press a button while sparring). <= 1
                # covers both "no real laps at all" and "just one real lap"
                # (per his own convention, lap 1 is always the warmup/
                # drilling lap, not a real round) -- either way there's no
                # manual ground truth to prefer over the auto-detected read.
                if real_lap_count <= 1:
                    hr_stream = garmin.fetch_activity_hr_stream(
                        client, activity.source_id, errors=errors
                    )
                    bjj_recording = config.get("bjj_recording", {})
                    segments = auto_detect_rounds(
                        activity.activity_id,
                        hr_stream,
                        round_duration_s=bjj_recording.get("round_duration_s", 300),
                        rest_duration_s=bjj_recording.get("rest_duration_s", 60),
                    )
                    # Replace, not just upsert: a re-fit that finds fewer segments (or
                    # none -- e.g. a non-5+1 session rejected by the detector's
                    # consistency check) must not leave stale segments behind. Only
                    # when the stream actually downloaded, so a transient fetch
                    # failure can't wipe a previously-good fit.
                    if hr_stream:
                        conn.execute(
                            "DELETE FROM activity_auto_segments WHERE activity_id = ?",
                            (activity.activity_id,),
                        )
                    for segment in segments:
                        db.upsert(
                            conn,
                            "activity_auto_segments",
                            segment.to_row(),
                            ["activity_id", "segment_index"],
                        )
                    if segments:
                        print(f"    auto-detected: {len(segments)} round/rest segment(s)")
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
    errors: list[str] = []
    try:
        for metric in health_auto_export.parse_body_composition(export_dir, errors=errors):
            rows_in += 1
            db.upsert(
                conn, "daily_metrics", metric.to_row(), ["date"], merge_json_columns=["sources"]
            )
            rows_upserted += 1
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
        print(f"health_auto_export: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    # `errors` here are per-record parse failures parse_weight() already
    # skipped past gracefully (bad unit, unparseable date) -- non-fatal, but
    # recorded rather than silently dropped.
    db.finish_ingest_run(
        conn,
        run_id,
        status="success",
        rows_in=rows_in,
        rows_upserted=rows_upserted,
        rows_skipped=0,
        errors=errors or None,
    )
    print(f"health_auto_export: {rows_upserted} rows upserted from {export_dir}")
    if errors:
        print(f"health_auto_export: {len(errors)} non-fatal warning(s) — see ingest_runs.errors")
    return True


def sync_renpho_csv(conn: sqlite3.Connection) -> bool:
    """RENPHO Health app CSV export — a manual, periodically-repeated export
    Francisco drops under `RENPHO_CSV_DIR` (default `data/raw/renpho/`)
    whenever he re-exports from the app, not a live automatic feed. Reading a
    fixed directory for any `*.csv` file (rather than a specific filename)
    means a future re-export needs no code change to pick up — same "read
    whatever's there" spirit as `sync_health_auto_export()`.

    Runs AFTER `sync_health_auto_export()` in `run_live_sync()` so it wins on
    overlapping body-composition fields for the same date, on every run —
    see `ingest/renpho_csv.py`'s module docstring for the real, investigated
    reason (the 2026-09-01 discrepancy): this CSV is read directly from
    RENPHO's own export, with no HealthKit relay in between to silently
    average same-day readings.
    """
    export_dir = Path(os.environ.get("RENPHO_CSV_DIR", DEFAULT_RENPHO_CSV_DIR))
    if not export_dir.exists() or not any(export_dir.glob("*.csv")):
        print(f"renpho_csv: no CSV export found under {export_dir} — skipping")
        return True

    run_id = db.start_ingest_run(conn, "renpho_csv")
    rows_in = rows_upserted = 0
    errors: list[str] = []
    try:
        for metric in renpho_csv.parse_body_composition(export_dir, errors=errors):
            rows_in += 1
            db.upsert(
                conn, "daily_metrics", metric.to_row(), ["date"], merge_json_columns=["sources"]
            )
            rows_upserted += 1
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
        print(f"renpho_csv: FAILED after {rows_upserted} rows — {exc}")
        traceback.print_exc()
        return False

    db.finish_ingest_run(
        conn,
        run_id,
        status="success",
        rows_in=rows_in,
        rows_upserted=rows_upserted,
        rows_skipped=0,
        errors=errors or None,
    )
    print(f"renpho_csv: {rows_upserted} dates upserted from {export_dir}")
    if errors:
        print(f"renpho_csv: {len(errors)} non-fatal warning(s) — see ingest_runs.errors")
    return True


@dataclass
class LiveSyncResult:
    """Outcome of one `run_live_sync()` call — every field a real, checked
    result, never invented (design principle 6): `dedupe` is the same
    `DedupeResult` `core/dedupe.py` already returns, not a re-summarized
    copy."""

    garmin_ok: bool
    health_auto_export_ok: bool
    renpho_csv_ok: bool
    dedupe: DedupeResult
    start_date: str
    end_date: str

    @property
    def ok(self) -> bool:
        return self.garmin_ok and self.health_auto_export_ok and self.renpho_csv_ok


def run_live_sync(
    conn: sqlite3.Connection, config: dict[str, Any], days: int = DEFAULT_WINDOW_DAYS
) -> LiveSyncResult:
    """Runs all three live sources for the trailing `days`-day window ending
    today (Europe/Madrid), then the cross-source dedup pass that always runs
    after ingestion regardless of per-source outcome (design principle 5) —
    the exact orchestration `scripts/sync.py`'s `main()` used to inline
    directly; now the one shared implementation for both that CLI entrypoint
    and `api/sync.py`'s manual "sync now" endpoint. `config` (athlete.yaml)
    is needed for `sync_garmin()`'s BJJ auto-round-detection step
    (`config["bjj_recording"]`, 2026-09-29).
    """
    end_date = today_local()
    start_date = end_date - timedelta(days=days - 1)

    garmin_ok = sync_garmin(conn, config, start_date, end_date)
    health_auto_export_ok = sync_health_auto_export(conn)
    renpho_csv_ok = sync_renpho_csv(conn)

    dedupe_result = dedupe_activities(conn)
    if dedupe_result.groups_merged:
        print(
            f"dedupe: merged {dedupe_result.groups_merged} duplicate group(s), "
            f"removed {dedupe_result.rows_deleted} row(s)"
        )
    else:
        print("dedupe: no duplicates found")
    if dedupe_result.fk_conflicts:
        print(
            f"dedupe: {len(dedupe_result.fk_conflicts)} loser row(s) left unmerged — "
            f"referenced by bjj_sessions.linked_activity_id or activity_laps.activity_id: "
            f"{dedupe_result.fk_conflicts}"
        )

    return LiveSyncResult(
        garmin_ok=garmin_ok,
        health_auto_export_ok=health_auto_export_ok,
        renpho_csv_ok=renpho_csv_ok,
        dedupe=dedupe_result,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )
