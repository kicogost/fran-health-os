"""Manual "sync now" endpoint — 2026-09-17.

Real trigger: Francisco opens the app most days and sees yesterday's data,
because the two scheduled launchd passes (07:00/09:30 morning, 21:30 quiet
sync — see CLAUDE.md's Phase 8 section) haven't fired yet by the time he
looks. A frontend refresh button alone wouldn't fix this — every page
already fetches fresh data from the API on load (no client-side cache to
bust), so a stale read means the *database* itself doesn't have today's data
yet, not that the browser is showing an old copy. This endpoint runs a real
sync on demand so the button actually pulls new data rather than re-reading
the same stale rows faster.

Reuses `health_os.ingest.live_sync.run_live_sync()` — the exact same
implementation `scripts/sync.py` runs on its schedule, extracted specifically
so this button and the launchd jobs can never independently drift (the same
"one real implementation" discipline `coach/briefing.py` and the `metrics/`
modules already follow across the CLI/API boundary elsewhere in this
project). Also recomputes `derived_daily` for the same window afterward
(`metrics/derived_daily.py`, the same functions `scripts/compute_derived.py`
calls) so a manual sync leaves the readiness/strain/baseline numbers current
too, not just the raw `daily_metrics`/`activities` rows.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any

from health_os.ingest.live_sync import DEFAULT_WINDOW_DAYS, run_live_sync
from health_os.metrics.derived_daily import compute_derived_metrics, store_derived_metrics


def run_manual_sync(
    conn: sqlite3.Connection, config: dict[str, Any], days: int = DEFAULT_WINDOW_DAYS
) -> dict[str, Any]:
    sync_result = run_live_sync(conn, days=days)

    dates = [d.isoformat() for d in _date_range(sync_result.start_date, sync_result.end_date)]
    derived_rows_written = 0
    for d in dates:
        metrics = compute_derived_metrics(conn, config, d)
        derived_rows_written += store_derived_metrics(conn, metrics)

    return {
        "status": "success" if sync_result.ok else "partial_failure",
        "synced_at": datetime.now(UTC).isoformat(),
        "window": {"start_date": sync_result.start_date, "end_date": sync_result.end_date},
        "sources": {
            "garmin": sync_result.garmin_ok,
            "health_auto_export": sync_result.health_auto_export_ok,
            "renpho_csv": sync_result.renpho_csv_ok,
        },
        "dedupe": {
            "groups_merged": sync_result.dedupe.groups_merged,
            "rows_deleted": sync_result.dedupe.rows_deleted,
        },
        "derived_metrics_rows_written": derived_rows_written,
    }


def _date_range(start_iso: str, end_iso: str) -> list[date]:
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
