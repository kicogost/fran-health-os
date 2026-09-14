"""RENPHO Health app CSV export ingestion — full body-composition detail
straight from the scale's own app, not relayed through HealthKit/Health Auto
Export (contrast `ingest/health_auto_export.py`, which only ever sees
whatever subset of metrics Apple Health happens to carry).

Francisco can export a CSV directly from the RENPHO Health app at any time
and drop it under `data/raw/renpho/` — a manual, periodically-repeated
export, not a live automatic feed like Health Auto Export, so this module
reads *any* `.csv` file found directly under the given directory (same
"read whatever's there, don't require a specific filename" spirit as
`health_auto_export.py`'s `HealthAutoExport-*.json` glob) rather than a
fixed filename.

Real format, verified directly against Francisco's actual export
(`data/raw/renpho/RENPHO Health-Francisco.csv`), not assumed:

    Date, Time, Weight(kg),BMI,Body Fat(%),Skeletal Muscle(%),Fat-Free
    Mass(kg),Subcutaneous Fat(%),Visceral Fat,Body Water(%),Muscle
    Mass(kg),Bone Mass(kg),Protein (%),BMR(kcal),Metabolic
    Age,Optimal Weight(kg),Target to optimal weight(kg),Target to optimal
    fat mass(kg),Target to optimal muscle mass(kg),Body Type,Remarks

    11/09/2026,04:32:59,79.50,25.5,24.8,48.5,59.78,22.0,9,54.3,56.76,3.02,
    17.1,1674,25,--, --, --, --, --, --

Real gotchas, verified rather than assumed:

- **Inconsistent header/value spacing**: a space follows some commas but
  not others (`"Date, Time, Weight(kg),BMI,..."` — note the literal space
  before `Time` and `Weight(kg)`, but not before `BMI`), and "Protein (%)"
  itself has a genuine internal space before its parenthesis (distinct from
  the comma-spacing issue). Parsed with `csv.DictReader(..., skipinitialspace
  =True)`, which strips exactly the comma-adjacent leading space on every
  field/header without touching a field's own internal spacing — verified
  this leaves "Protein (%)" intact as a single lookup key rather than
  "Protein" + " (%)" or similar mangling.
- **`Date` is DD/MM/YYYY, not MM/DD/YYYY** — confirmed unambiguously by real
  rows in Francisco's export with a day-of-month above 12 (e.g. "13/04/2026"),
  which would raise on parsing as MM/DD (no 13th month) and only makes sense
  as day-first.
- **`Time` carries no timezone offset at all** — same shape already solved
  once for Strava's bulk-export `Activity Date` column
  (`core/timezones.py: localize_to_utc()`), reused here unchanged rather than
  reinventing local-time handling. Confirmed Europe/Madrid local wall-clock
  time by cross-checking real overlapping dates against `daily_metrics` rows
  already populated by the Garmin/Apple-Health pipelines for the same dates —
  the CSV's own recorded times (mostly early morning, e.g. 07:xx-08:xx) are
  exactly the kind of time a home weigh-in happens at, consistent with
  Europe/Madrid local time rather than UTC or another offset.
- **Many dates have multiple rows** (a re-weigh seconds later, or a
  genuinely different reading hours apart). This project's established
  "latest reading per date wins, never averaged" rule
  (`ingest/apple_health.py`/`ingest/health_auto_export.py`) is applied
  **per whole row**, not per field independently: every field in one CSV row
  comes from the same physical weigh-in event, so the row with the latest
  `Time` for a date is selected as a unit and ALL of its present fields are
  used together — mixing, say, an evening row's weight with a morning row's
  body-fat% would fabricate a reading that never actually happened, which is
  exactly what design principle 6 rules out.
- **`--` means genuinely missing**, e.g. a reading that captured weight/BMI
  but failed the bioimpedance measurement (every other field `--` that row).
  Parsed as `None`, never as zero or invented.
- **`Optimal Weight(kg)`/`Target to optimal ...`/`Body Type`/`Remarks`** are
  deliberately NOT ingested — confirmed by direct inspection that every real
  row in Francisco's export has `--` in all of them. A genuine checked-empty
  gap, not a silent omission.
- **`Fat-Free Mass(kg)` reuses the existing `lean_body_mass_kg` column**
  (migration 0005, populated via the Apple-Health path) rather than a new
  one — cross-checked directly against 4 real overlapping dates already in
  `daily_metrics` and found to match exactly every time (see migration 0007's
  own header comment for the specific numbers). "Fat-Free Mass" and "Lean
  Body Mass" are standard synonyms for the same body-composition quantity,
  and this real cross-check confirms it's genuinely the same number here.

**A real, investigated discrepancy** (2026-09-01, see CLAUDE.md for the full
writeup): the CSV has three rows for this date — a fasted 05:59 morning
reading (78.95 kg) and two near-identical 21:1x evening rows (83.75 kg,
a duplicate double-tap of the same reading). `daily_metrics` already held
82.15 kg for this date from the Apple-Health/Health-Auto-Export path — a
THIRD number matching neither CSV row. 82.15 is, to ~10 significant figures,
the unweighted mean of all three CSV readings ((78.95 + 83.75 + 83.75) / 3 =
82.15, confirmed by direct calculation) — essentially certain to be the real
explanation rather than coincidence (an unrelated fourth reading landing
exactly on the arithmetic mean of the other three is astronomically
unlikely). The most likely mechanism: Health Auto Export's own per-day
aggregation (or the HealthKit statistics query underneath it) collapsed
multiple same-day `weight_body_mass` samples into a same-day AVERAGE rather
than passing through the latest discrete sample — something this codebase's
own `ingest/health_auto_export.py` never does on its own side (verified:
that parser has no averaging code at all, it just takes whatever single
`qty` is in each data-array entry). Whatever the exact upstream mechanism,
an averaged value silently standing in for a single day's weight is itself a
design-principle-6 violation ("no silent interpolation, no gap-filling with
averages") — which is precisely why this CSV, read directly from RENPHO's
own export with no relay in between, is treated as MORE authoritative than
the Health-Auto-Export/Apple-Health path for any date both cover. This
module's ingestion is wired in *after* `health_auto_export.py` in both
`scripts/backfill.py` and `scripts/sync.py` so it wins on conflicting scalar
fields for the same date, consistently on every future run — not just this
one. Applying this project's own "latest row wins" rule to the CSV itself
picks the 83.75 kg evening row for 2026-09-01 (it's later than the 05:59
morning row) — a real, physically plausible post-food/water/clothed evening
weight, not an error to second-guess further.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from health_os.core.models import DailyMetric
from health_os.core.timezones import localize_to_utc, to_local_date

_FILE_GLOB = "*.csv"
_MISSING = "--"
_DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S"  # DD/MM/YYYY -- verified, see module docstring

# RENPHO CSV header name -> DailyMetric field name. Optimal-weight/target/body-type/
# remarks columns are deliberately excluded (see module docstring: every real row has
# "--" in all of them).
_FIELD_MAP: dict[str, str] = {
    "Weight(kg)": "weight_kg",
    "BMI": "bmi",
    "Body Fat(%)": "body_fat_pct",
    "Skeletal Muscle(%)": "skeletal_muscle_pct",
    "Fat-Free Mass(kg)": "lean_body_mass_kg",  # reused, not a new column -- see docstring
    "Subcutaneous Fat(%)": "subcutaneous_fat_pct",
    "Visceral Fat": "visceral_fat_rating",
    "Body Water(%)": "body_water_pct",
    "Muscle Mass(kg)": "muscle_mass_kg",
    "Bone Mass(kg)": "bone_mass_kg",
    "Protein (%)": "protein_pct",  # note the literal internal space before "(%)"
    "BMR(kcal)": "bmr_kcal",
    "Metabolic Age": "metabolic_age",
}
_INT_FIELDS = {"visceral_fat_rating", "bmr_kcal", "metabolic_age"}
_SOURCE_TAG = "renpho_csv"


def _parse_field(raw: str | None, *, as_int: bool) -> float | int | None:
    """`--` (or blank) means genuinely missing -> `None`, never 0 or invented."""
    text = (raw or "").strip()
    if not text or text == _MISSING:
        return None
    value = float(text)
    return int(round(value)) if as_int else value


def _row_values(row: dict[str, str]) -> dict[str, float | int]:
    values: dict[str, float | int] = {}
    for header_name, field in _FIELD_MAP.items():
        parsed = _parse_field(row.get(header_name), as_int=field in _INT_FIELDS)
        if parsed is not None:
            values[field] = parsed
    return values


def parse_body_composition(
    export_dir: Path, *, errors: list[str] | None = None
) -> Iterator[DailyMetric]:
    """Yield one `DailyMetric` per local date across every `*.csv` file found
    directly under `export_dir`.

    For a date with multiple rows, the row with the latest `Time` wins as a
    whole unit (see module docstring) — never averaged, and never a per-field
    mix of different rows. One malformed row (an unparseable date/time, a
    non-numeric value where a real number was expected) is skipped and
    appended to `errors` rather than discarding every other valid row in the
    file, matching `ingest/health_auto_export.py`'s per-record isolation.
    """
    # local_date -> (row's own UTC timestamp, that row's field values)
    latest_row_by_date: dict[str, tuple[datetime, dict[str, float | int]]] = {}

    for path in sorted(Path(export_dir).glob(_FILE_GLOB)):
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, skipinitialspace=True)
            for line_num, row in enumerate(reader, start=2):  # header occupies line 1
                date_raw = (row.get("Date") or "").strip()
                time_raw = (row.get("Time") or "").strip()
                if not date_raw or not time_raw:
                    continue
                try:
                    naive_local = datetime.strptime(f"{date_raw} {time_raw}", _DATETIME_FORMAT)
                    dt_utc = localize_to_utc(naive_local)
                    values = _row_values(row)
                except (ValueError, TypeError) as exc:
                    if errors is not None:
                        errors.append(f"{path.name}:{line_num}: {exc}")
                    continue
                if not values:
                    continue

                local_date = to_local_date(dt_utc)
                existing = latest_row_by_date.get(local_date)
                if existing is None or dt_utc > existing[0]:
                    latest_row_by_date[local_date] = (dt_utc, values)

    for local_date, (_dt_utc, values) in sorted(latest_row_by_date.items()):
        sources: dict[str, Any] = dict.fromkeys(values, _SOURCE_TAG)
        yield DailyMetric(date=local_date, sources=sources, **values)
