"""Apple Health export parser (kickoff doc section 2.2, Phase 2).

Streams `<export_dir>/export.xml` with `lxml.etree.iterparse` — per the kickoff
doc's explicit warning, never `ElementTree.parse` (a real export is hundreds of MB;
loading it whole exhausts RAM). Verified against Francisco's actual 464MB export
(2026-08-27): streaming + clearing each element after use parsed 1.1M elements in
~5.5s with flat memory use.

Apple Health mostly duplicates Garmin (which syncs into it), so per design this
module deliberately extracts only two things, not the whole export:

1. **Workouts** (`<Workout>` elements) -> `activities`, filtered to drop known
   duplicate/foreign sources (see `config/sources.yaml`). This is broader than
   just BJJ — any workout logged here (Nike Run Club, StrongLifts, Runna,
   BJJBuddy, native Watch workouts, ...) becomes an `activities` row; Phase 3
   reconciles overlap with Garmin/Strava once those are loaded too.
2. **Body mass** (`HKQuantityTypeIdentifierBodyMass` records) -> `daily_metrics.
   weight_kg`, restricted to an *allowlist* of known-scale source names (Renpho) —
   unlike workouts, weight is a denylist-flips-to-allowlist case: a wrong weight
   source is easy to get silently wrong, so only the known scale counts.

Steps, sleep, and HR data are NOT ingested from Apple Health in this pass — the
kickoff doc's own guidance (section 2.2) is that Apple Health only adds value for
watch-not-worn movement data and non-Garmin third-party apps, which requires
comparing against Garmin's own daily data to know which is which. That
reconciliation is Phase 3's job (`core/dedupe.py`) and Garmin's bulk export hasn't
landed yet — building partial step/sleep logic now would just need reworking once
it does. See CLAUDE.md's Phase 2 status note.

Real-export findings verified against Francisco's actual export (2026-08-27), not
assumed:
- Every timestamp carries an explicit offset, e.g. "2026-08-21 07:32:00 +0200" —
  parsed directly, no cross-checking needed (contrast with Strava's CSV).
- `<Workout>` elements in this export version have no natural unique ID — a
  `source_id` is synthesized from (source, start, end, type) via
  `ingest.common.synthetic_source_id`.
- No reliable inline heart-rate summary was found on real `<Workout>` elements
  (checked both BJJBuddy- and native-Watch-recorded workouts) — `avg_hr`/`max_hr`
  are left `None` for Apple-Health-sourced activities rather than guessed at.
- Multiple non-Francisco/duplicate sources are mixed into the same export: Garmin
  syncs in as sourceName "Connect", Strava as sourceName "Strava", and a family
  member's watch appears as "Apple Watch de roberta" — all excluded per
  `config/sources.yaml`.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

from health_os.core.models import Activity, DailyMetric
from health_os.core.timezones import to_local_date, to_utc_iso
from health_os.ingest.common import normalize_sport_name, synthetic_source_id

_DEFAULT_SOURCES_YAML = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"

_BODY_MASS_TYPE = "HKQuantityTypeIdentifierBodyMass"
_APPLE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S %z"
_DISTANCE_TO_M = {"km": 1000.0, "mi": 1609.344, "m": 1.0, "meters": 1.0}
_WEIGHT_TO_KG = {"kg": 1.0, "lb": 0.453_592_37, "lbs": 0.453_592_37}


@dataclass(slots=True, frozen=True)
class AppleHealthSourceConfig:
    """The `apple_health` section of `config/sources.yaml`, typed."""

    exclude_source_names: frozenset[str]
    exclude_source_name_substrings: tuple[str, ...]
    weight_source_names: frozenset[str]

    @classmethod
    def from_yaml(cls, path: Path | None = None) -> AppleHealthSourceConfig:
        with Path(path or _DEFAULT_SOURCES_YAML).open(encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
        section = data["apple_health"]
        return cls(
            exclude_source_names=frozenset(section.get("exclude_source_names", [])),
            exclude_source_name_substrings=tuple(
                s.lower() for s in section.get("exclude_source_name_substrings", [])
            ),
            weight_source_names=frozenset(section.get("weight_source_names", [])),
        )


def is_excluded_source(source_name: str, config: AppleHealthSourceConfig) -> bool:
    if source_name in config.exclude_source_names:
        return True
    lowered = source_name.lower()
    return any(substring in lowered for substring in config.exclude_source_name_substrings)


def _parse_apple_datetime(raw: str) -> datetime:
    return datetime.strptime(raw, _APPLE_DATETIME_FORMAT)


def _convert_distance_to_m(value: float, unit: str) -> float:
    factor = _DISTANCE_TO_M.get(unit)
    if factor is None:
        raise ValueError(f"unrecognized distance unit: {unit!r}")
    return value * factor


def _convert_weight_to_kg(value: float, unit: str) -> float:
    factor = _WEIGHT_TO_KG.get(unit)
    if factor is None:
        raise ValueError(f"unrecognized weight unit: {unit!r}")
    return value * factor


def _clear_element(elem: etree._Element) -> None:
    """Free a streamed element's memory (kickoff doc's iterparse warning)."""
    elem.clear()
    while elem.getprevious() is not None:
        del elem.getparent()[0]


def _workout_to_activity(elem: etree._Element) -> Activity | None:
    start_raw = elem.get("startDate")
    end_raw = elem.get("endDate")
    source_name = elem.get("sourceName")
    activity_type = elem.get("workoutActivityType")
    if not start_raw or not end_raw or not source_name or not activity_type:
        return None

    start_dt = _parse_apple_datetime(start_raw)
    end_dt = _parse_apple_datetime(end_raw)
    start_utc = to_utc_iso(start_dt)

    distance_m = None
    total_distance = elem.get("totalDistance")
    if total_distance:
        distance_m = _convert_distance_to_m(
            float(total_distance), elem.get("totalDistanceUnit") or "km"
        )

    source_id = synthetic_source_id(source_name, start_raw, end_raw, activity_type)

    return Activity(
        activity_id=Activity.make_id("apple_health", source_id),
        source="apple_health",
        source_id=source_id,
        start_utc=start_utc,
        local_date=to_local_date(start_utc),
        sport=normalize_sport_name(activity_type),
        duration_s=int((end_dt - start_dt).total_seconds()),
        distance_m=distance_m,
    )


def parse_workouts(
    export_dir: Path, config: AppleHealthSourceConfig | None = None
) -> Iterator[Activity]:
    """Yield one `Activity` per non-excluded `<Workout>` in `<export_dir>/export.xml`."""
    config = config or AppleHealthSourceConfig.from_yaml()
    xml_path = Path(export_dir) / "export.xml"
    for _, elem in etree.iterparse(str(xml_path), events=("end",), tag="Workout"):
        try:
            source_name = elem.get("sourceName") or ""
            if is_excluded_source(source_name, config):
                continue
            activity = _workout_to_activity(elem)
            if activity is not None:
                yield activity
        finally:
            _clear_element(elem)


def parse_daily_weight(
    export_dir: Path, config: AppleHealthSourceConfig | None = None
) -> Iterator[DailyMetric]:
    """Yield one `DailyMetric` per local date with a body-mass record from a known
    scale (`config.weight_source_names`). When a date has more than one reading,
    the latest one wins — never averaged or otherwise invented (design principle
    6): two readings 16 seconds apart are almost certainly a sync retry of the
    same weigh-in, not two real measurements.
    """
    config = config or AppleHealthSourceConfig.from_yaml()
    xml_path = Path(export_dir) / "export.xml"

    latest_by_date: dict[str, tuple[datetime, float, str]] = {}
    for _, elem in etree.iterparse(str(xml_path), events=("end",), tag="Record"):
        try:
            if elem.get("type") != _BODY_MASS_TYPE:
                continue
            source_name = elem.get("sourceName") or ""
            if source_name not in config.weight_source_names:
                continue
            value_raw = elem.get("value")
            start_raw = elem.get("startDate")
            if value_raw is None or not start_raw:
                continue

            start_dt = _parse_apple_datetime(start_raw)
            weight_kg = _convert_weight_to_kg(float(value_raw), elem.get("unit") or "kg")
            local_date = to_local_date(to_utc_iso(start_dt))

            existing = latest_by_date.get(local_date)
            if existing is None or start_dt > existing[0]:
                latest_by_date[local_date] = (start_dt, weight_kg, source_name)
        finally:
            _clear_element(elem)

    for local_date, (_, weight_kg, source_name) in sorted(latest_by_date.items()):
        yield DailyMetric(
            date=local_date,
            weight_kg=weight_kg,
            sources={"weight_kg": f"apple_health:{source_name.lower()}"},
        )
