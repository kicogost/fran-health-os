#!/usr/bin/env python3
"""Log the daily illness_log entry: whatever symptom info is actually known
that day, so illness episodes accumulate for a future correlation against
HRV/RHR/sleep/training-load (metrics/correlations.py, once enough real
episodes exist — MIN_N=30, not wired in yet, deliberately).

    uv run python scripts/log_illness.py
    uv run python scripts/log_illness.py --sore-throat --fatigue-weakness --congestion \
        --likely-cause "unclear -- possibly allergies" --notes "..."

One row per DATE, not per episode — a run of consecutive dated entries reads
as one episode after the fact, no separate start/end field needed. Every
field is optional and never defaulted — a symptom not mentioned stays
`None`, never invented as False. Upserts on date: logging today twice
updates it rather than duplicating.
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
from health_os.core.models import IllnessLog  # noqa: E402

_SYMPTOM_LABELS = {
    "sore_throat": "Sore throat",
    "fever": "Feels feverish (self-assessed, not measured)",
    "congestion": "Congestion (runny/blocked nose)",
    "cough": "Cough",
    "body_aches": "Body aches",
    "fatigue_weakness": "Fatigue/weakness beyond normal training fatigue",
    "headache": "Headache",
}


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


def _prompt_int_optional(label: str, *, lo: int, hi: int) -> int | None:
    while True:
        raw = _prompt(f"{label} ({lo}-{hi}, blank to skip)", required=False)
        if not raw:
            return None
        try:
            val = int(raw)
        except ValueError:
            print("  must be a whole number.")
            continue
        if not lo <= val <= hi:
            print(f"  must be between {lo} and {hi}.")
            continue
        return val


def _prompt_float_optional(label: str) -> float | None:
    raw = _prompt(label, required=False)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print("  not a number, skipping.")
        return None


def _prompt_bool_optional(label: str) -> bool | None:
    raw = _prompt(f"{label} (y/n, blank to skip)", required=False).lower()
    if not raw:
        return None
    return raw.startswith("y")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", help="YYYY-MM-DD, default today (Europe/Madrid)")
    parser.add_argument(
        "--severity", type=int, default=None, help="1 (barely noticeable) - 10 (severe)"
    )
    parser.add_argument("--sore-throat", dest="sore_throat", action="store_true", default=None)
    parser.add_argument("--no-sore-throat", dest="sore_throat", action="store_false")
    parser.add_argument("--fever", action="store_true", default=None)
    parser.add_argument("--no-fever", dest="fever", action="store_false")
    parser.add_argument("--temperature", dest="temperature_c", type=float, default=None, help="°C")
    parser.add_argument("--congestion", action="store_true", default=None)
    parser.add_argument("--no-congestion", dest="congestion", action="store_false")
    parser.add_argument("--cough", action="store_true", default=None)
    parser.add_argument("--no-cough", dest="cough", action="store_false")
    parser.add_argument("--body-aches", dest="body_aches", action="store_true", default=None)
    parser.add_argument("--no-body-aches", dest="body_aches", action="store_false")
    parser.add_argument(
        "--fatigue-weakness", dest="fatigue_weakness", action="store_true", default=None
    )
    parser.add_argument("--no-fatigue-weakness", dest="fatigue_weakness", action="store_false")
    parser.add_argument("--headache", action="store_true", default=None)
    parser.add_argument("--no-headache", dest="headache", action="store_false")
    parser.add_argument("--likely-cause", dest="likely_cause", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--db-path", default=None)
    return parser


def _any_flag_set(args: argparse.Namespace) -> bool:
    fields = (
        "severity",
        "sore_throat",
        "fever",
        "temperature_c",
        "congestion",
        "cough",
        "body_aches",
        "fatigue_weakness",
        "headache",
        "likely_cause",
        "notes",
    )
    return any(getattr(args, f) is not None for f in fields)


def resolve_entry(args: argparse.Namespace) -> IllnessLog:
    """Flag mode if any content flag was passed, interactive otherwise --
    same shape as log_wellness.py, since every field here is genuinely
    optional day to day (some days it's just a couple of symptoms, some
    days a temperature reading and nothing else).
    """
    date = args.date or _today_madrid()

    if _any_flag_set(args):
        return IllnessLog(
            date=date,
            severity=args.severity,
            sore_throat=args.sore_throat,
            fever=args.fever,
            temperature_c=args.temperature_c,
            congestion=args.congestion,
            cough=args.cough,
            body_aches=args.body_aches,
            fatigue_weakness=args.fatigue_weakness,
            headache=args.headache,
            likely_cause=args.likely_cause,
            notes=args.notes,
        )

    date = _prompt("Date (YYYY-MM-DD)", date)
    severity = _prompt_int_optional(
        "Overall severity (1 = barely noticeable, 10 = severe/incapacitated)", lo=1, hi=10
    )
    print("Symptoms (y/n, blank to skip any):")
    sore_throat = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['sore_throat']}")
    fever = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['fever']}")
    temperature_c = _prompt_float_optional("Measured temperature in °C (blank if not taken)")
    congestion = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['congestion']}")
    cough = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['cough']}")
    body_aches = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['body_aches']}")
    fatigue_weakness = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['fatigue_weakness']}")
    headache = _prompt_bool_optional(f"  {_SYMPTOM_LABELS['headache']}")
    likely_cause = (
        _prompt("Likely cause (your own guess, e.g. viral/allergies)", required=False) or None
    )
    notes = _prompt("Notes", required=False) or None

    return IllnessLog(
        date=date,
        severity=severity,
        sore_throat=sore_throat,
        fever=fever,
        temperature_c=temperature_c,
        congestion=congestion,
        cough=cough,
        body_aches=body_aches,
        fatigue_weakness=fatigue_weakness,
        headache=headache,
        likely_cause=likely_cause,
        notes=notes,
    )


def _warn_if_overwriting(conn: sqlite3.Connection, entry: IllnessLog) -> None:
    existing = conn.execute(
        "SELECT severity FROM illness_log WHERE date = ?", (entry.date,)
    ).fetchone()
    if existing is not None:
        prior = existing["severity"]
        print(f"Updating existing entry for {entry.date} (was severity={prior})")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        entry = resolve_entry(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    conn = db.init_db(args.db_path)
    try:
        _warn_if_overwriting(conn, entry)
        db.upsert(conn, "illness_log", entry.to_row(), ["date"])
    finally:
        conn.close()

    print(f"Logged: {entry.date}", end="")
    if entry.severity is not None:
        print(f", severity={entry.severity}/10")
    else:
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
