"""Strava bulk-archive backfill parser (kickoff doc section 2.3, Phase 2).

Parses the CSV index of a Strava data-export archive (Settings -> My Account ->
Download or Delete Your Account -> Request your archive). Reads `activities.csv`
only — its summary columns (duration, distance, HR, power, elevation, even a
`Training Load` column) already cover everything the `activities` table needs, so
the per-activity `.fit.gz`/`.gpx` files under `activities/` are not parsed in this
pass. If activity-level HR-zone or stream data is ever needed, that's a separate,
later addition — not required for the historical backfill.

Real-export gotchas below are verified against Francisco's actual archive
(2026-08-27), not assumed from Strava's docs — see kickoff doc section 2.1's
warning that "the parsing will be uglier than the docs suggest."

- The header has 5 DUPLICATE column names (Elapsed Time, Distance, Max Heart Rate,
  Relative Effort, Commute each appear twice — 103 columns total). Confirmed
  identical in every row checked. Parsed by column INDEX, not name — a plain
  `csv.DictReader` would silently drop one of each pair.
- `Activity Date` carries NO timezone offset at all, e.g. "Aug 22, 2026, 6:52:17
  AM". Verified via each row's own sunrise/sunset epoch columns that the implied
  local sunrise/sunset times land correctly for Mallorca in that season — this is
  Europe/Madrid local time, not UTC. Do not change this assumption without
  re-verifying the same way against a fresh export.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from health_os.core.models import Activity
from health_os.core.timezones import localize_to_utc, to_local_date, to_utc_iso
from health_os.ingest.common import normalize_sport_name

# Column indices in activities.csv. Named constants because the header has
# duplicate names at several indices — these pick the specific occurrence that's
# actually reliable (see module docstring).
_COL_ACTIVITY_ID = 0
_COL_ACTIVITY_DATE = 1
_COL_ACTIVITY_TYPE = 3
_COL_ELAPSED_TIME_S = 5
_COL_ELEVATION_GAIN_M = 20
_COL_DISTANCE_M = 17  # meters; the other "Distance" (idx 6) is km, same value
_COL_MAX_HR = 30
_COL_AVG_HR = 31
_COL_AVG_WATTS = 33
_COL_PERCEIVED_EXERTION = 43
_COL_WEIGHTED_AVG_POWER = 46
_COL_TRAINING_LOAD = 88

EXPECTED_HEADER_LEN = 103

_ACTIVITY_DATE_FORMAT = "%b %d, %Y, %I:%M:%S %p"


def _to_float(raw: str) -> float | None:
    return float(raw) if raw not in ("", None) else None


def _to_int(raw: str) -> int | None:
    val = _to_float(raw)
    return int(val) if val is not None else None


def _parse_activity_date(raw: str) -> str:
    """See module docstring: Europe/Madrid local time, no offset in the CSV."""
    naive = datetime.strptime(raw, _ACTIVITY_DATE_FORMAT)
    return to_utc_iso(localize_to_utc(naive))


def _row_to_activity(row: list[str]) -> Activity | None:
    activity_id = row[_COL_ACTIVITY_ID].strip()
    if not activity_id or not row[_COL_ACTIVITY_DATE]:
        return None

    start_utc = _parse_activity_date(row[_COL_ACTIVITY_DATE])
    activity_type = row[_COL_ACTIVITY_TYPE]

    return Activity(
        activity_id=Activity.make_id("strava", activity_id),
        source="strava",
        source_id=activity_id,
        start_utc=start_utc,
        local_date=to_local_date(start_utc),
        sport=normalize_sport_name(activity_type) if activity_type else None,
        duration_s=_to_int(row[_COL_ELAPSED_TIME_S]),
        distance_m=_to_float(row[_COL_DISTANCE_M]),
        avg_hr=_to_int(row[_COL_AVG_HR]),
        max_hr=_to_int(row[_COL_MAX_HR]),
        training_load=_to_float(row[_COL_TRAINING_LOAD]),
        avg_power=_to_float(row[_COL_AVG_WATTS]) or _to_float(row[_COL_WEIGHTED_AVG_POWER]),
        elevation_gain_m=_to_float(row[_COL_ELEVATION_GAIN_M]),
        perceived_rpe=_to_int(row[_COL_PERCEIVED_EXERTION]),
    )


def parse_activities_csv(export_dir: Path) -> Iterator[Activity]:
    """Yield one `Activity` per row of `<export_dir>/activities.csv`.

    Raises `ValueError` if the header shape doesn't match what was verified
    against a real export — fail loudly on a format change rather than silently
    misreading columns by the wrong index.
    """
    csv_path = Path(export_dir) / "activities.csv"
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if len(header) != EXPECTED_HEADER_LEN:
            raise ValueError(
                f"{csv_path} has {len(header)} columns, expected {EXPECTED_HEADER_LEN}. "
                "Strava's export format may have changed — verify the column "
                "indices in strava_bulk.py against the new header before trusting "
                "this parse."
            )
        for row in reader:
            activity = _row_to_activity(row)
            if activity is not None:
                yield activity
