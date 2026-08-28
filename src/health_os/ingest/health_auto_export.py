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

Only the `weight_body_mass` metric is extracted, into `daily_metrics.
weight_kg` — `lean_body_mass`/`body_mass_index` are present in the app's
"Body Mass" bundle but have no column in our schema; known, not-invented gap,
not silently dropped without a reason on record. Applies the exact same
allowlist-by-source-name policy as the bulk XML ingester
(`config/sources.yaml: apple_health.weight_source_names`) by importing
`AppleHealthSourceConfig` directly rather than duplicating it, and the same
"latest reading per date wins, never averaged" rule (design principle 6) as
`ingest/apple_health.py: parse_daily_weight()`.

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
down to Body Mass only. `parse_weight()` only ever looks for the
`weight_body_mass` metric name in any file it's handed and ignores everything
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

_WEIGHT_METRIC_NAME = "weight_body_mass"
_FILE_GLOB = "HealthAutoExport-*.json"
# Identical to apple_health.py's native-export datetime shape — verified
# directly (fromisoformat rejects it; strptime with %z does not) rather than
# assumed just because both call themselves "ISO-ish".
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_WEIGHT_TO_KG = {"kg": 1.0, "lb": 0.453_592_37, "lbs": 0.453_592_37}


def _parse_datetime(raw: str) -> datetime:
    return datetime.strptime(raw, _DATETIME_FORMAT)


def _convert_weight_to_kg(value: float, unit: str) -> float:
    factor = _WEIGHT_TO_KG.get(unit)
    if factor is None:
        raise ValueError(f"unrecognized weight unit: {unit!r}")
    return value * factor


def parse_weight(
    export_dir: Path, config: AppleHealthSourceConfig | None = None
) -> Iterator[DailyMetric]:
    """Yield one `DailyMetric` per local date with a `weight_body_mass`
    reading from a known scale, across every `HealthAutoExport-*.json` file
    found directly under `export_dir`.

    Reads *all* matching files, not just the newest — the app can produce
    several per automation run (a "Week" range plus whatever daily files
    already existed), and their date coverage can legitimately overlap. The
    latest-wins rule is applied across the combined set exactly as if it were
    one file, so overlap is harmless rather than something that has to be
    pre-filtered by the caller.
    """
    config = config or AppleHealthSourceConfig.from_yaml()
    latest_by_date: dict[str, tuple[datetime, float, str]] = {}

    for path in sorted(Path(export_dir).glob(_FILE_GLOB)):
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        for metric in payload.get("data", {}).get("metrics", []):
            if metric.get("name") != _WEIGHT_METRIC_NAME:
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

                dt = _parse_datetime(date_raw)
                weight_kg = _convert_weight_to_kg(float(qty), unit)
                local_date = to_local_date(to_utc_iso(dt))

                existing = latest_by_date.get(local_date)
                if existing is None or dt > existing[0]:
                    latest_by_date[local_date] = (dt, weight_kg, source_name)

    for local_date, (_, weight_kg, source_name) in sorted(latest_by_date.items()):
        yield DailyMetric(
            date=local_date,
            weight_kg=weight_kg,
            sources={"weight_kg": f"apple_health:{source_name.lower()}"},
        )
