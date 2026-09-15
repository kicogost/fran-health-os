#!/usr/bin/env python3
"""Log a general health-history record: a bloodwork result, a medical event
(condition/injury/surgery/hospitalization), a medication/supplement course,
an allergy, or a family medical history entry.

These are occasional, low-frequency historical records — logged a handful of
times a year, not a daily habit like log_bjj.py/log_wellness.py — a
structurally different kind of entry from every other logger in this
project. One unified script with a `--kind` flag routes to the right table,
rather than five separate script names to remember for something this rare.

Interactive (no flags — prompts which category first, then walks its fields):

    uv run python scripts/log_health_history.py

Flag mode (pass --kind plus that category's fields):

    uv run python scripts/log_health_history.py --kind bloodwork \\
        --test-name ferritin --value 85 --unit ng/mL --range-low 30 --range-high 400

    uv run python scripts/log_health_history.py --kind medical_event \\
        --title "Right knee ACL tear" --event-category injury --status ongoing \\
        --date 2018-03-01

    uv run python scripts/log_health_history.py --kind medication \\
        --name "Vitamin D3" --med-type supplement --dosage "2000 IU" --frequency daily

    uv run python scripts/log_health_history.py --kind allergy \\
        --allergen peanuts --severity moderate --reaction hives

    uv run python scripts/log_health_history.py --kind family_history \\
        --relation mother --condition hypertension

`--kind` is what puts this in flag mode — every other flag belongs to one
specific category, so pass it alongside `--kind`, not instead of it.

Bloodwork/medical_event/medication have NO natural key — design principle 2
(raw data is immutable) reads most literally here as "log a fresh record
every time": every call INSERTS a new row, never upserts, never warns about
overwriting (there's nothing to overwrite — a second blood draw or a new
diagnosis note is a genuinely new fact). Allergy (natural key: `allergen`)
and family_history (natural key: `relation`+`condition`) DO upsert and warn
before overwriting, same as every other natural-keyed logger in this
project (log_measurement.py, log_illness.py, ...).

Bloodwork's interactive mode specifically LOOPS: one blood draw produces many
test values sharing one date, so it prompts for the draw date once, then one
test at a time (blank test name ends the panel) — logging a full panel in one
sitting. Flag mode logs exactly one test value per invocation.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from health_os.core import db  # noqa: E402
from health_os.core.models import (  # noqa: E402
    Allergy,
    BloodworkResult,
    FamilyMedicalHistory,
    MedicalEvent,
    MedicationSupplement,
)

KINDS = ("bloodwork", "medical_event", "medication", "allergy", "family_history")
EVENT_CATEGORIES = ("condition", "injury", "surgery", "hospitalization", "other")
EVENT_STATUSES = ("ongoing", "resolved", "unknown")
MEDICATION_TYPES = ("medication", "supplement")
ALLERGY_SEVERITIES = ("mild", "moderate", "severe")

_TABLE_FOR_KIND = {
    "bloodwork": "bloodwork_results",
    "medical_event": "medical_events",
    "medication": "medications_supplements",
    "allergy": "allergies",
    "family_history": "family_medical_history",
}

# (cli flag, argparse dest) pairs required to treat a --kind invocation as
# complete flag mode -- mirrors log_bjj.py's "all-or-nothing, fail fast
# listing what's missing" pattern rather than partially prompting.
_REQUIRED_FLAGS: dict[str, tuple[tuple[str, str], ...]] = {
    "bloodwork": (("--test-name", "test_name"), ("--value", "value")),
    "medical_event": (
        ("--title", "title"),
        ("--event-category", "event_category"),
        ("--status", "status"),
    ),
    "medication": (("--name", "name"), ("--med-type", "med_type")),
    "allergy": (("--allergen", "allergen"),),
    "family_history": (("--relation", "relation"), ("--condition", "condition")),
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


def _prompt_choice(label: str, choices: tuple[str, ...], default: str | None = None) -> str:
    while True:
        val = _prompt(f"{label} ({'/'.join(choices)})", default)
        if val in choices:
            return val
        print(f"  must be one of: {', '.join(choices)}")


def _prompt_choice_optional(label: str, choices: tuple[str, ...]) -> str | None:
    while True:
        raw = _prompt(f"{label} ({'/'.join(choices)}, blank to skip)", required=False)
        if not raw:
            return None
        if raw in choices:
            return raw
        print(f"  must be one of: {', '.join(choices)}")


def _prompt_float(label: str) -> float:
    while True:
        raw = _prompt(label)
        try:
            return float(raw)
        except ValueError:
            print("  must be a number.")


def _prompt_float_optional(label: str) -> float | None:
    raw = _prompt(label, required=False)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        print("  not a number, skipping.")
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kind", choices=KINDS, default=None, help="which category to log")
    parser.add_argument(
        "--date", default=None, help="YYYY-MM-DD -- draw/event date, default today (Europe/Madrid)"
    )
    parser.add_argument("--notes", default=None)
    parser.add_argument("--db-path", default=None)

    # --- bloodwork ---
    parser.add_argument("--test-name", dest="test_name", default=None)
    parser.add_argument("--value", type=float, default=None)
    parser.add_argument("--unit", default=None)
    parser.add_argument("--range-low", dest="reference_range_low", type=float, default=None)
    parser.add_argument("--range-high", dest="reference_range_high", type=float, default=None)

    # --- medical event ---
    parser.add_argument("--title", default=None)
    parser.add_argument(
        "--event-category", dest="event_category", choices=EVENT_CATEGORIES, default=None
    )
    parser.add_argument("--status", choices=EVENT_STATUSES, default=None)
    parser.add_argument("--resolved-date", dest="resolved_date", default=None)

    # --- medication / supplement ---
    parser.add_argument("--name", default=None)
    parser.add_argument("--med-type", dest="med_type", choices=MEDICATION_TYPES, default=None)
    parser.add_argument("--dosage", default=None)
    parser.add_argument("--frequency", default=None)
    parser.add_argument("--start-date", dest="start_date", default=None)
    parser.add_argument("--end-date", dest="end_date", default=None)

    # --- allergy ---
    parser.add_argument("--allergen", default=None)
    parser.add_argument("--reaction", default=None)
    parser.add_argument("--severity", choices=ALLERGY_SEVERITIES, default=None)
    parser.add_argument("--date-identified", dest="date_identified", default=None)

    # --- family history ---
    parser.add_argument("--relation", default=None)
    parser.add_argument("--condition", default=None)

    return parser


def _from_flags(kind: str, args: argparse.Namespace) -> Any:
    if kind == "bloodwork":
        return BloodworkResult(
            date=args.date or _today_madrid(),
            test_name=args.test_name,
            value=args.value,
            unit=args.unit,
            reference_range_low=args.reference_range_low,
            reference_range_high=args.reference_range_high,
            notes=args.notes,
        )
    if kind == "medical_event":
        return MedicalEvent(
            date=args.date or _today_madrid(),
            category=args.event_category,
            title=args.title,
            status=args.status,
            resolved_date=args.resolved_date,
            notes=args.notes,
        )
    if kind == "medication":
        return MedicationSupplement(
            name=args.name,
            type=args.med_type,
            dosage=args.dosage,
            frequency=args.frequency,
            start_date=args.start_date or _today_madrid(),
            end_date=args.end_date,
            notes=args.notes,
        )
    if kind == "allergy":
        return Allergy(
            allergen=args.allergen,
            reaction=args.reaction,
            severity=args.severity,
            date_identified=args.date_identified,
            notes=args.notes,
        )
    if kind == "family_history":
        return FamilyMedicalHistory(
            relation=args.relation, condition=args.condition, notes=args.notes
        )
    raise AssertionError(f"unhandled kind: {kind!r}")


def _interactive_bloodwork() -> list[BloodworkResult]:
    date = _prompt("Draw date (YYYY-MM-DD)", _today_madrid())
    print("Enter each test value one at a time (blank test name to finish the panel):")
    results: list[BloodworkResult] = []
    while True:
        test_name = _prompt("  Test name", required=False)
        if not test_name:
            break
        value = _prompt_float("    Value")
        unit = _prompt("    Unit (e.g. ng/mL, nmol/L)", required=False) or None
        range_low = _prompt_float_optional("    Reference range low (blank to skip)")
        range_high = _prompt_float_optional("    Reference range high (blank to skip)")
        notes = _prompt("    Notes", required=False) or None
        results.append(
            BloodworkResult(
                date=date,
                test_name=test_name,
                value=value,
                unit=unit,
                reference_range_low=range_low,
                reference_range_high=range_high,
                notes=notes,
            )
        )
        print(f"    added: {test_name} = {value}" + (f" {unit}" if unit else ""))
    return results


def _interactive_medical_event() -> MedicalEvent:
    date = _prompt("Date (YYYY-MM-DD)", _today_madrid())
    category = _prompt_choice("Category", EVENT_CATEGORIES, "condition")
    title = _prompt("Title (short description)")
    status = _prompt_choice("Status", EVENT_STATUSES, "ongoing")
    resolved_date = (
        _prompt("Resolved date (YYYY-MM-DD)", _today_madrid()) if status == "resolved" else None
    )
    notes = _prompt("Notes", required=False) or None
    return MedicalEvent(
        date=date,
        category=category,
        title=title,
        status=status,
        resolved_date=resolved_date,
        notes=notes,
    )


def _interactive_medication() -> MedicationSupplement:
    name = _prompt("Name")
    med_type = _prompt_choice("Type", MEDICATION_TYPES, "supplement")
    dosage = _prompt("Dosage (e.g. 500mg, 2 capsules)", required=False) or None
    frequency = _prompt("Frequency (e.g. daily, as needed)", required=False) or None
    start_date = _prompt("Start date (YYYY-MM-DD)", _today_madrid())
    end_date = _prompt("End date (YYYY-MM-DD, blank if still taking)", required=False) or None
    notes = _prompt("Notes", required=False) or None
    return MedicationSupplement(
        name=name,
        type=med_type,
        dosage=dosage,
        frequency=frequency,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
    )


def _interactive_allergy() -> Allergy:
    allergen = _prompt("Allergen")
    reaction = _prompt("Reaction", required=False) or None
    severity = _prompt_choice_optional("Severity", ALLERGY_SEVERITIES)
    date_identified = (
        _prompt("Date identified (YYYY-MM-DD, blank if unknown)", required=False) or None
    )
    notes = _prompt("Notes", required=False) or None
    return Allergy(
        allergen=allergen,
        reaction=reaction,
        severity=severity,
        date_identified=date_identified,
        notes=notes,
    )


def _interactive_family_history() -> FamilyMedicalHistory:
    relation = _prompt("Relation (e.g. mother, paternal grandfather)")
    condition = _prompt("Condition")
    notes = _prompt("Notes", required=False) or None
    return FamilyMedicalHistory(relation=relation, condition=condition, notes=notes)


def _resolve_interactive() -> tuple[str, list[Any]]:
    kind = _prompt_choice("What are you logging", KINDS, "bloodwork")
    if kind == "bloodwork":
        return kind, list(_interactive_bloodwork())
    if kind == "medical_event":
        return kind, [_interactive_medical_event()]
    if kind == "medication":
        return kind, [_interactive_medication()]
    if kind == "allergy":
        return kind, [_interactive_allergy()]
    if kind == "family_history":
        return kind, [_interactive_family_history()]
    raise AssertionError(f"unhandled kind: {kind!r}")


def resolve_entries(args: argparse.Namespace) -> tuple[str, list[Any]]:
    """Flag mode (exactly one entry) if `--kind` was passed, interactive
    otherwise. Unlike log_illness.py/log_wellness.py (every field genuinely
    optional day to day), each category here has a real minimum set of
    required fields, so `--kind` triggers an all-or-nothing check for that
    category's required flags, same shape as log_bjj.py.
    """
    if args.kind is None:
        return _resolve_interactive()

    missing = [flag for flag, attr in _REQUIRED_FLAGS[args.kind] if getattr(args, attr) is None]
    if missing:
        raise SystemExit(
            f"--kind {args.kind} also needs {', '.join(missing)} "
            "(or omit --kind entirely for interactive prompts)."
        )
    return args.kind, [_from_flags(args.kind, args)]


def _warn_if_overwriting_allergy(conn: sqlite3.Connection, allergy: Allergy) -> None:
    existing = conn.execute(
        "SELECT severity FROM allergies WHERE allergen = ?", (allergy.allergen,)
    ).fetchone()
    if existing is not None:
        print(
            f"Updating existing allergy entry for {allergy.allergen!r} (was severity="
            f"{existing['severity']})"
        )


def _warn_if_overwriting_family_history(
    conn: sqlite3.Connection, entry: FamilyMedicalHistory
) -> None:
    existing = conn.execute(
        "SELECT notes FROM family_medical_history WHERE relation = ? AND condition = ?",
        (entry.relation, entry.condition),
    ).fetchone()
    if existing is not None:
        print(
            f"Updating existing family history entry for {entry.relation!r} / {entry.condition!r}"
        )


def _save_entry(conn: sqlite3.Connection, kind: str, entry: Any) -> None:
    if kind == "allergy":
        _warn_if_overwriting_allergy(conn, entry)
        db.upsert(conn, "allergies", entry.to_row(), ["allergen"])
    elif kind == "family_history":
        _warn_if_overwriting_family_history(conn, entry)
        db.upsert(conn, "family_medical_history", entry.to_row(), ["relation", "condition"])
    else:
        # bloodwork / medical_event / medication: no natural key -- a fresh,
        # independent record every time (design principle 2), never an upsert.
        db.insert(conn, _TABLE_FOR_KIND[kind], entry.to_row())


def _print_summary(kind: str, entry: Any) -> None:
    if kind == "bloodwork":
        line = f"Logged: {entry.date} {entry.test_name} = {entry.value}"
        if entry.unit:
            line += f" {entry.unit}"
        print(line)
    elif kind == "medical_event":
        print(f"Logged: {entry.date} [{entry.category}] {entry.title} ({entry.status})")
    elif kind == "medication":
        span = f"from {entry.start_date}" + (
            f" to {entry.end_date}" if entry.end_date else " (ongoing)"
        )
        print(f"Logged: {entry.name} ({entry.type}) {span}")
    elif kind == "allergy":
        suffix = f" ({entry.severity})" if entry.severity else ""
        print(f"Logged: {entry.allergen}{suffix}")
    elif kind == "family_history":
        print(f"Logged: {entry.relation} — {entry.condition}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        kind, entries = resolve_entries(args)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    if not entries:
        print("Nothing logged.")
        return 0

    conn = db.init_db(args.db_path)
    try:
        for entry in entries:
            _save_entry(conn, kind, entry)
            _print_summary(kind, entry)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
