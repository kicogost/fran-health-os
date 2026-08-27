"""Helpers shared by more than one ingester.

Anything genuinely per-source (CSV column indices, XML tag names, ...) belongs in
that source's own module. This file is only for the mechanical bits every parser
independently needs: normalizing a sport/activity-type label into
`activities.sport`, and minting a stable synthetic `source_id` for sources whose
records don't carry a natural external ID.
"""

from __future__ import annotations

import hashlib
import re

_CAMEL_BOUNDARY_RE = re.compile(r"(?<!^)(?=[A-Z])")


def normalize_sport_name(raw: str) -> str:
    """Snake-case a sport/activity-type label for the `activities.sport` column.

    Strips a leading "HKWorkoutActivityType" prefix (Apple HealthKit's constant
    naming) if present, then converts CamelCase or "Title Case" to snake_case:
    "HKWorkoutActivityTypeMartialArts" -> "martial_arts", "Weight Training" ->
    "weight_training", "Rock Climb" -> "rock_climb".
    """
    s = raw.removeprefix("HKWorkoutActivityType").replace(" ", "")
    return _CAMEL_BOUNDARY_RE.sub("_", s).lower()


def synthetic_source_id(*parts: str) -> str:
    """A stable, deterministic ID for a record with no natural external ID.

    Apple Health `<Workout>` elements (unlike Strava's numeric Activity ID or
    Garmin's activity ID) carry nothing that uniquely identifies them across
    re-parses of the same export — so the ID is derived from the fields that do
    (source, start, end, type), letting `db.upsert()` stay idempotent per design
    principle 4: re-running the backfill against the same export produces the same
    IDs, not duplicate rows.
    """
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
