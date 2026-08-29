"""Health Auto Export weight ingestion — the "live" Apple Health path
(CLAUDE.md's Data sources section). This is NOT the native Health app's
`export.xml` format — see `ingest/apple_health.py` for that one-time bulk
parser. Health Auto Export (a third-party iOS app, premium tier) produces its
own JSON schema entirely, and the two must never be confused: the format was
verified directly against a real exported file from Francisco's account
(2026-08-28), not assumed from the app's marketing/docs.

Real format, verified:
    {
      "data": {
        "metrics": [
          {
            "name": "weight_body_mass",
            "units": "kg",
            "data": [
              {"qty": 78.45, "date": "2026-08-21 00:00:00 +0200", "source": "RENPHO Health"}
            ]
          },
          {"name": "lean_body_mass", ...},
          {"name": "body_mass_index", ...}
        ]
      }
    }

Extracts three metrics from the same "Body Mass" bundle: `weight_body_mass`
-> `daily_metrics.weight_kg`, `lean_body_mass` -> `.lean_body_mass_kg`,
`body_mass_index` -> `.bmi`. The latter two were originally left
unextracted ("known, not-invented gap, not silently dropped without a
reason on record") until Francisco asked directly (2026-08-29) whether
Apple Health surfaces Renpho's body-composition data — checked against the
real live export rather than assumed: `body_fat_percentage` is NOT present
anywhere in it (Renpho likely computes it in its own app but doesn't push
it to HealthKit on this scale/account), but lean mass and BMI are, so those
two are now real, ingested columns. All three apply the exact same
allowlist-by-source-name policy as the bulk XML ingester
(`config/sources.yaml: apple_health.weight_source_names`) by importing
`AppleHealthSourceConfig` directly rather than duplicating it — a wrong
source is just as much a problem for lean mass as for weight, since both
come from the same physical scale reading. Same "latest reading per date
wins, never averaged" rule (design principle 6) as
`ingest/apple_health.py: parse_daily_weight()`, tracked independently per
field per date since the three metrics aren't always all present for the
same date (e.g. a date can have weight + BMI but no lean mass reading).

Real-export gotcha, verified by testing rather than assumed: the `date`
field's format — `"2026-08-21 00:00:00 +0200"` (space before a colon-less
offset) — is byte-for-byte the same shape the native `export.xml` uses (both
ultimately come from HealthKit's own date serialization), so the same
`datetime.strptime(..., "%Y-%m-%d %H:%M:%S %z")` approach works unchanged.
`datetime.fromisoformat` does NOT accept this shape (rejects the space before
the offset) — confirmed directly in a REPL, not assumed to "just work" because
it looks ISO-ish.

Real cross-check against Francisco's actual account (2026-08-28): a
"Week"-range export (Health Auto Export names date-range files by ISO week
number when the range isn't a single day, e.g. `HealthAutoExport-2026-34.json`
for ISO week 34) reported 78.45 kg on 2026-08-21, source "RENPHO Health" —
exactly matching the figure already in the database from the historical
export.xml backfill. Real end-to-end correctness signal, not just internal
consistency.

The app also produced two much larger files during initial setup
(`HealthAutoExport-2026-08-27.json`, `-08-28.json`, ~370KB-1.1MB) containing
7-12 unrelated metrics (`heart_rate`, `sleep_analysis`, `step_count`, ...)
from before the automation's "Select Health Metrics" setting was narrowed
down to Body Mass only. `parse_body_composition()` only ever looks for the
three metric names above in any file it's handed and ignores everything
else, so those stray files are harmless to leave in the input directory —
not just historically explained, actually inert.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from health_os.core.models import DailyMetric
from health_os.core.timezones import to_local_date, to_utc_iso
from health_os.ingest.apple_health import AppleHealthSourceConfig

_FILE_GLOB = "HealthAutoExport-*.json"
# Identical to apple_health.py's native-export datetime shape — verified
# directly (fromisoformat rejects it; strptime with %z does not) rather than
# assumed just because both call themselves "ISO-ish".
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_WEIGHT_TO_KG = {"kg": 1.0, "lb": 0.453_592_37, "lbs": 0.453_592_37}

# Health Auto Export metric name -> DailyMetric field name. All three ride
# in the same "Body Mass" bundle (verified against Francisco's real export,
# 2026-08-29) -- body_fat_percentage was checked for and is NOT present, so
# it isn't listed here (not a silent omission -- see module docstring).
_METRIC_FIELD_MAP = {
    "weight_body_mass": "weight_kg",
    "lean_body_mass": "lean_body_mass_kg",
    "body_mass_index": "bmi",
}
# Only these two fields carry a mass unit (kg/lb) needing conversion; BMI's
# "units" value is "count" (a dimensionless ratio) -- taken as-is.
_MASS_FIELDS = {"weight_kg", "lean_body_mass_kg"}


def _parse_datetime(raw: str) -> datetime:
    return datetime.strptime(raw, _DATETIME_FORMAT)


def _convert_weight_to_kg(value: float, unit: str) -> float:
    factor = _WEIGHT_TO_KG.get(unit)
    if factor is None:
        raise ValueError(f"unrecognized weight unit: {unit!r}")
    return value * factor


def parse_body_composition(
    export_dir: Path,
    config: AppleHealthSourceConfig | None = None,
    *,
    errors: list[str] | None = None,
) -> Iterator[DailyMetric]:
    """Yield one `DailyMetric` per local date with any of weight/lean body
    mass/BMI from a known scale, across every `HealthAutoExport-*.json` file
    found directly under `export_dir`. (Renamed from `parse_weight` 2026-08-29
    when lean mass/BMI extraction was added — same function, wider scope.)

    Reads *all* matching files, not just the newest — the app can produce
    several per automation run (a "Week" range plus whatever daily files
    already existed), and their date coverage can legitimately overlap. The
    latest-wins rule is applied across the combined set exactly as if it were
    one file, so overlap is harmless rather than something that has to be
    pre-filtered by the caller. Tracked independently per field per date (not
    one shared latest-timestamp per date) since the three metrics aren't
    always all present together — e.g. a real date can have weight + BMI but
    no lean mass reading that day.

    A `DailyMetric` is only yielded with the fields that actually had a real
    reading for that date; the others are left `None` (never invented) —
    `to_row()`'s "omit `None` by default" behavior then means this never
    clobbers a field some other source already populated for the same date.

    One malformed reading (an unrecognized weight unit, an unparseable date)
    is skipped and appended to `errors` rather than aborting the whole run —
    fixed as a real bug 2026-08-28: this used to raise uncaught on the first
    bad entry anywhere in any file, discarding every OTHER already-parsed
    valid reading from every file in the directory, not just the bad one.
    """
    config = config or AppleHealthSourceConfig.from_yaml()
    # local_date -> field -> (timestamp, value, source_name)
    latest_by_date: dict[str, dict[str, tuple[datetime, float, str]]] = {}

    for path in sorted(Path(export_dir).glob(_FILE_GLOB)):
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        for metric in payload.get("data", {}).get("metrics", []):
            field = _METRIC_FIELD_MAP.get(metric.get("name"))
            if field is None:
                continue
            unit = metric.get("units") or "kg"
            for entry in metric.get("data", []):
                source_name = entry.get("source") or ""
                if source_name not in config.weight_source_names:
                    continue
                qty = entry.get("qty")
                date_raw = entry.get("date")
                if qty is None or not date_raw:
                    continue

                try:
                    dt = _parse_datetime(date_raw)
                    value = float(qty)
                    if field in _MASS_FIELDS:
                        value = _convert_weight_to_kg(value, unit)
                except (ValueError, TypeError) as exc:
                    if errors is not None:
                        errors.append(f"{path.name}: bad {field} entry {entry!r} — {exc}")
                    continue
                local_date = to_local_date(to_utc_iso(dt))

                by_field = latest_by_date.setdefault(local_date, {})
                existing = by_field.get(field)
                if existing is None or dt > existing[0]:
                    by_field[field] = (dt, value, source_name)

    for local_date, by_field in sorted(latest_by_date.items()):
        values = {field: value for field, (_, value, _src) in by_field.items()}
        sources = {
            field: f"apple_health:{source_name.lower()}"
            for field, (_, _value, source_name) in by_field.items()
        }
        yield DailyMetric(date=local_date, sources=sources, **values)
