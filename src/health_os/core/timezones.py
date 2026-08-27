"""Timezone helpers shared by every ingester (design principle 7).

Store UTC in the database, always. This module is the one place that converts a
UTC timestamp into a local calendar date for `local_date`-style attribution
columns (`activities.local_date`, and the sleep wake-date rule below) — every
ingester should go through here rather than doing its own timezone arithmetic, so
DST transitions are handled the same way everywhere instead of drifting between
Garmin/Apple Health/Strava-specific code.

Deliberately independent of any export file's format — this is pure date math, so
it doesn't need to wait on real bulk-export files to get built and tested.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Madrid"


def parse_utc(value: str | datetime) -> datetime:
    """Parse an ISO8601 timestamp, or pass through an existing datetime.

    Requires the result to carry a UTC offset — a naive datetime is a bug at the
    call site (some upstream parser dropped the offset), not something to
    silently assume is UTC. Converts non-UTC-but-aware timestamps to UTC.
    """
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"expected a timezone-aware timestamp, got naive: {value!r}")
    return dt.astimezone(UTC)


def to_local_date(utc_value: str | datetime, tz_name: str = DEFAULT_TZ) -> str:
    """Convert a UTC timestamp to its local calendar date (YYYY-MM-DD), DST-aware."""
    local = parse_utc(utc_value).astimezone(ZoneInfo(tz_name))
    return local.date().isoformat()


def attribute_sleep_to_wake_date(sleep_end_utc: str | datetime, tz_name: str = DEFAULT_TZ) -> str:
    """The local calendar date a sleep session is attributed to: the wake date.

    Design principle 7: a session starting 23:40 and ending 07:10 attributes to
    the wake-up day, not the day the athlete fell asleep. Always pass the
    session's END timestamp here, not its start.
    """
    return to_local_date(sleep_end_utc, tz_name)
