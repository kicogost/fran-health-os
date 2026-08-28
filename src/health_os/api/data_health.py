"""Assembles the Data Health page's payload — freshness per field, missing
days, the dedupe log, and recent ingest runs. Mirrors
`dashboard/views/data_health.py` exactly; per that module's own docstring,
"not optional — this is how pipeline breakage gets noticed rather than
silently going stale," so this page isn't a nice-to-have among the six.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from typing import Any

from health_os.core.timezones import to_local_date

FRESHNESS_FIELDS = {
    "weight_kg": "Weight",
    "hrv_overnight_ms": "HRV",
    "resting_hr": "RHR",
    "sleep_total_min": "Sleep",
    "training_readiness": "Training readiness",
}

MISSING_DAYS_WINDOW = 30
INGEST_RUNS_LIMIT = 100


def _today_local() -> str:
    return to_local_date(datetime.now(UTC))


def _freshness(conn: sqlite3.Connection, today: str) -> list[dict[str, Any]]:
    rows = []
    for field, label in FRESHNESS_FIELDS.items():
        row = conn.execute(
            f"SELECT MAX(date) AS d FROM daily_metrics WHERE {field} IS NOT NULL"  # noqa: S608
        ).fetchone()
        last_date = row["d"] if row else None
        if last_date is None:
            rows.append({"field": field, "label": label, "status": "no_data", "last_date": None})
            continue
        days_stale = (date.fromisoformat(today) - date.fromisoformat(last_date)).days
        rows.append(
            {
                "field": field,
                "label": label,
                "status": "today" if days_stale == 0 else f"{days_stale}d ago",
                "last_date": last_date,
                "days_stale": days_stale,
            }
        )
    return rows


def _missing_days(conn: sqlite3.Connection) -> list[str]:
    max_row = conn.execute("SELECT MAX(date) AS d FROM daily_metrics").fetchone()
    if max_row["d"] is None:
        return []
    end = date.fromisoformat(max_row["d"])
    start = end - timedelta(days=MISSING_DAYS_WINDOW - 1)
    present = {
        r["date"]
        for r in conn.execute(
            "SELECT DISTINCT date FROM daily_metrics WHERE date >= ? AND date <= ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    }
    expected = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    return [d for d in expected if d not in present]


def _dedupe_log(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT activity_id, source, local_date, sport, merged_from FROM activities "
        "WHERE merged_from IS NOT NULL AND merged_from != '[]' ORDER BY local_date DESC"
    ).fetchall()
    return [
        {
            "activity_id": r["activity_id"],
            "source": r["source"],
            "local_date": r["local_date"],
            "sport": r["sport"],
            "merged_from": json.loads(r["merged_from"]),
        }
        for r in rows
    ]


def _ingest_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, source, started_at, finished_at, status, rows_in, rows_upserted, "
        "rows_skipped, errors FROM ingest_runs ORDER BY started_at DESC LIMIT ?",
        (INGEST_RUNS_LIMIT,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "source": r["source"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "status": r["status"],
            "rows_in": r["rows_in"],
            "rows_upserted": r["rows_upserted"],
            "rows_skipped": r["rows_skipped"],
            "errors": json.loads(r["errors"]) if r["errors"] else None,
        }
        for r in rows
    ]


def build_data_health_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    """Everything the Data Health page needs, as one JSON-ready dict."""
    today = _today_local()
    return {
        "freshness": _freshness(conn, today),
        "missing_days": _missing_days(conn),
        "missing_days_window": MISSING_DAYS_WINDOW,
        "dedupe_log": _dedupe_log(conn),
        "ingest_runs": _ingest_runs(conn),
    }
