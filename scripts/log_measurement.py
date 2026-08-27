#!/usr/bin/env python3
"""Log a body measurement — waist by default (kickoff doc schema section 5).

    uv run python scripts/log_measurement.py                       # interactive, waist
    uv run python scripts/log_measurement.py --value 85.5           # flag mode, waist
    uv run python scripts/log_measurement.py --value 85.5 --date 2026-08-30

Baseline waist is 86 cm (config/athlete.yaml), measured Sunday, fasted, below
navel — matching that protocol each week is what makes the trend meaningful, not
just logging *a* number. Upserts on (date, measurement_type): logging the same
type again for the same date updates it rather than duplicating.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.core.models import BodyMeasurement  # noqa: E402


def _today_madrid() -> str:
    return datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()


def _prompt(label: str, default: str | None = None, *, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{label}{suffix}: ").strip()
        if not raw and default is not None:
            return default
        if not raw and not required:
            return ""
        if raw:
            return raw
        print("  required.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument("--type", dest="measurement_type", default=None, help="default: waist")
    parser.add_argument("--value", type=float, help="cm")
    parser.add_argument("--notes", default=None)
    parser.add_argument("--db-path", default=None)
    return parser


def resolve_measurement(args: argparse.Namespace) -> BodyMeasurement:
    interactive = args.value is None

    if interactive:
        date = _prompt("Date (YYYY-MM-DD)", args.date or _today_madrid())
        measurement_type = _prompt("Measurement type", args.measurement_type or "waist")
        value_raw = _prompt(f"{measurement_type} (cm)")
        try:
            value_cm = float(value_raw)
        except ValueError as exc:
            raise SystemExit(f"'{value_raw}' isn't a number") from exc
        notes = _prompt("Notes", required=False) or None
    else:
        date = args.date or _today_madrid()
        measurement_type = args.measurement_type or "waist"
        value_cm = args.value
        notes = args.notes

    return BodyMeasurement(
        date=date, measurement_type=measurement_type, value_cm=value_cm, notes=notes
    )


def _warn_if_overwriting(conn: sqlite3.Connection, m: BodyMeasurement) -> None:
    existing = conn.execute(
        "SELECT value_cm FROM body_measurements WHERE date = ? AND measurement_type = ?",
        (m.date, m.measurement_type),
    ).fetchone()
    if existing is not None:
        print(
            f"Updating existing {m.measurement_type} for {m.date} (was: {existing['value_cm']} cm)"
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        measurement = resolve_measurement(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    conn = db.init_db(args.db_path)
    try:
        _warn_if_overwriting(conn, measurement)
        db.upsert(conn, "body_measurements", measurement.to_row(), ["date", "measurement_type"])
    finally:
        conn.close()

    print(f"Logged: {measurement.date} {measurement.measurement_type} = {measurement.value_cm} cm")
    if measurement.notes:
        print(f"  notes: {measurement.notes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
