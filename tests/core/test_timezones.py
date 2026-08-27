from __future__ import annotations

from datetime import UTC, datetime

import pytest

from health_os.core.timezones import (
    attribute_sleep_to_wake_date,
    localize_to_utc,
    parse_utc,
    to_local_date,
    to_utc_iso,
)


class TestParseUtc:
    def test_accepts_z_suffix(self) -> None:
        dt = parse_utc("2026-08-27T17:00:00Z")
        assert dt == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)

    def test_accepts_explicit_offset(self) -> None:
        dt = parse_utc("2026-08-27T19:00:00+02:00")
        assert dt == datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)

    def test_passes_through_aware_datetime(self) -> None:
        dt = datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)
        assert parse_utc(dt) == dt

    def test_rejects_naive_datetime(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            parse_utc(datetime(2026, 8, 27, 17, 0, 0))

    def test_rejects_naive_string(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            parse_utc("2026-08-27T17:00:00")


class TestToLocalDate:
    def test_winter_offset_crosses_midnight(self) -> None:
        # Madrid is CET (UTC+1) in January. 23:30 UTC -> 00:30 local, next day.
        assert to_local_date("2026-01-15T23:30:00Z") == "2026-01-16"

    def test_summer_offset_crosses_midnight(self) -> None:
        # Madrid is CEST (UTC+2) in July. 22:30 UTC -> 00:30 local, next day.
        assert to_local_date("2026-07-15T22:30:00Z") == "2026-07-16"

    def test_no_offset_no_date_change(self) -> None:
        assert to_local_date("2026-08-27T10:00:00Z") == "2026-08-27"

    def test_other_timezone(self) -> None:
        assert to_local_date("2026-08-27T23:30:00Z", tz_name="America/New_York") == "2026-08-27"


class TestAttributeSleepToWakeDate:
    def test_uses_end_not_start(self) -> None:
        # Falls asleep 23:40 local (21:40 UTC, CEST = UTC+2), wakes 07:10 local
        # (05:10 UTC) the next day. Must attribute to the wake date, not the
        # date the session started.
        wake_date = attribute_sleep_to_wake_date("2026-08-27T05:10:00Z")
        assert wake_date == "2026-08-27"
        # Sanity check against the (wrong) start-date attribution this guards against.
        start_date_wrongly = to_local_date("2026-08-26T21:40:00Z")
        assert start_date_wrongly == "2026-08-26"
        assert wake_date != start_date_wrongly


class TestLocalizeToUtc:
    def test_summer_local_to_utc(self) -> None:
        # 6:52:17 local Madrid time in August (CEST, UTC+2) -> 4:52:17 UTC.
        # This is the real Strava CSV case: "Aug 22, 2026, 6:52:17 AM", no offset.
        naive = datetime(2026, 8, 22, 6, 52, 17)
        assert localize_to_utc(naive) == datetime(2026, 8, 22, 4, 52, 17, tzinfo=UTC)

    def test_winter_local_to_utc(self) -> None:
        # January is CET, UTC+1.
        naive = datetime(2026, 1, 15, 9, 0, 0)
        assert localize_to_utc(naive) == datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)

    def test_rejects_aware_datetime(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            localize_to_utc(datetime(2026, 8, 22, 6, 52, 17, tzinfo=UTC))


class TestToUtcIso:
    def test_formats_with_z_suffix(self) -> None:
        assert to_utc_iso(datetime(2026, 8, 27, 17, 0, 0, tzinfo=UTC)) == "2026-08-27T17:00:00Z"

    def test_converts_non_utc_offset(self) -> None:
        assert to_utc_iso("2026-08-27T19:00:00+02:00") == "2026-08-27T17:00:00Z"
