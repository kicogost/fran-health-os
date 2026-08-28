#!/usr/bin/env python3
"""Compute and persist the Phase 4 derived-metric suite into `derived_daily`
(kickoff doc section 6 / CLAUDE.md's "Derived metrics"): HRV/RHR baselines,
sleep debt, CTL/ATL/TSB, monotony/strain, weight trend, comp countdown, and
the readiness score. Every number here has been computable since 2026-08-28
but nothing ever wrote a row to `derived_daily` until this script existed —
see `metrics/derived_daily.py`'s module docstring for the full reasoning.

    uv run python scripts/compute_derived.py                 # trailing 3 days
    uv run python scripts/compute_derived.py --days 7
    uv run python scripts/compute_derived.py --date 2026-08-20  # one specific date

Trailing window (default 3 days), same reasoning as `scripts/sync.py`: a
delayed Garmin correction (HRV computed late, a firmware backfill) can
change an already-synced day's inputs after the fact, so recomputing a
short trailing window on every run self-heals that for free. `--date`
overrides this with exactly one date (for backfilling history or spot-
checking a specific day) rather than a window ending there.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from health_os.core import db  # noqa: E402
from health_os.core.timezones import to_local_date  # noqa: E402
from health_os.metrics.derived_daily import (  # noqa: E402
    compute_derived_metrics,
    store_derived_metrics,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "athlete.yaml"
DEFAULT_WINDOW_DAYS = 3


def _today_local() -> date:
    return date.fromisoformat(to_local_date(datetime.now(UTC)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"trailing window size in days, inclusive of today (default {DEFAULT_WINDOW_DAYS})",
    )
    parser.add_argument(
        "--date", default=None, help="compute exactly this one YYYY-MM-DD date instead of a window"
    )
    parser.add_argument("--db-path", default=None, help="Override HEALTH_OS_DB_PATH")
    args = parser.parse_args(argv)

    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: '{args.date}' isn't a valid YYYY-MM-DD date.")
            return 1
        dates = [args.date]
    else:
        end_date = _today_local()
        start_date = end_date - timedelta(days=args.days - 1)
        dates = [
            (start_date + timedelta(days=i)).isoformat()
            for i in range((end_date - start_date).days + 1)
        ]

    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    conn = db.init_db(args.db_path)
    try:
        run_id = db.start_ingest_run(conn, "compute_derived")
        rows_written = 0
        try:
            for d in dates:
                metrics = compute_derived_metrics(conn, config, d)
                rows_written += store_derived_metrics(conn, metrics)
                readiness = next((m for m in metrics if m.metric_name == "readiness_score"), None)
                has_score = readiness and readiness.value is not None
                score_str = f"{readiness.value:.1f}" if has_score else "n/a"
                print(f"  {d}: {len(metrics)} metric(s) written, readiness_score={score_str}")
        except Exception as exc:  # noqa: BLE001 - reported to ingest_runs, not swallowed
            db.finish_ingest_run(
                conn, run_id, status="failed", rows_upserted=rows_written, errors=[str(exc)]
            )
            print(f"compute_derived: FAILED after {rows_written} rows — {exc}")
            raise
        db.finish_ingest_run(conn, run_id, status="success", rows_upserted=rows_written)
        print(f"compute_derived: {rows_written} row(s) written across {len(dates)} date(s)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
