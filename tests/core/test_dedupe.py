from __future__ import annotations

import json
import sqlite3

from health_os.core import db as db_module
from health_os.core.dedupe import _is_match, _sport_family, dedupe_activities
from health_os.core.models import Activity


def _insert(conn: sqlite3.Connection, **overrides) -> Activity:
    defaults = dict(
        source="strava",
        source_id="1",
        start_utc="2026-08-27T17:00:00Z",
        local_date="2026-08-27",
        sport="ride",
        duration_s=3600,
    )
    defaults.update(overrides)
    activity = Activity(
        activity_id=Activity.make_id(defaults["source"], defaults["source_id"]), **defaults
    )
    db_module.upsert(conn, "activities", activity.to_row(), ["source", "source_id"])
    return activity


class TestSportFamily:
    def test_known_mappings(self) -> None:
        assert _sport_family("ride") == _sport_family("cycling") == "cycling"
        assert (
            _sport_family("workout") == _sport_family("functional_strength_training") == "strength"
        )

    def test_strength_training_maps_to_strength(self) -> None:
        # Real gap found 2026-08-30: a Strava "weight_training" + Garmin
        # "strength_training" pair for the identical gym session never
        # reached either matching tier because this label had no mapping.
        assert _sport_family("strength_training") == _sport_family("weight_training") == "strength"

    def test_running_variants_map_to_running(self) -> None:
        assert (
            _sport_family("trail_running")
            == _sport_family("treadmill_running")
            == _sport_family("run")
            == "running"
        )

    def test_lap_swimming_maps_to_swimming(self) -> None:
        assert _sport_family("lap_swimming") == _sport_family("swim") == "swimming"

    def test_unmapped_sport_is_its_own_family(self) -> None:
        assert _sport_family("underwater_basket_weaving") == "underwater_basket_weaving"

    def test_none_is_unknown(self) -> None:
        assert _sport_family(None) == "unknown"


class TestIsMatch:
    def _row(self, **kw):
        from health_os.core.dedupe import _Row

        defaults = dict(
            activity_id="x",
            source="strava",
            source_id="1",
            local_date="2026-08-27",
            start_utc="2026-08-27T17:00:00Z",
            duration_s=3600,
            sport="ride",
            avg_hr=None,
            merged_from=[],
        )
        defaults.update(kw)
        return _Row(**defaults)

    def test_matches_within_tolerance(self) -> None:
        a = self._row(source="strava")
        b = self._row(
            source="apple_health", start_utc="2026-08-27T17:01:59Z", duration_s=3659
        )  # 119s start diff, 59s duration diff
        assert _is_match(a, b) is True

    def test_start_time_just_outside_tolerance(self) -> None:
        a = self._row(source="strava")
        b = self._row(source="apple_health", start_utc="2026-08-27T17:02:01Z")  # 121s
        assert _is_match(a, b) is False

    def test_duration_just_outside_tolerance(self) -> None:
        a = self._row(source="strava")
        b = self._row(source="apple_health", duration_s=3661)  # 61s diff
        assert _is_match(a, b) is False

    def test_different_local_date_never_matches(self) -> None:
        a = self._row(source="strava")
        b = self._row(source="apple_health", local_date="2026-08-28")
        assert _is_match(a, b) is False

    def test_same_source_never_matches(self) -> None:
        a = self._row(source="strava")
        b = self._row(source="strava", source_id="2")
        assert _is_match(a, b) is False

    def test_incompatible_sport_family_does_not_match(self) -> None:
        a = self._row(source="strava", sport="ride")
        b = self._row(source="apple_health", sport="running")
        assert _is_match(a, b) is False

    def test_exact_avg_hr_matches_despite_start_and_duration_mismatch(self) -> None:
        # Real case, 2026-08-30: 8 real Strava/Garmin ride pairs in
        # Francisco's account never merged under the primary rule -- start
        # times differ by exactly 2 hours (confirmed real, not an ingestion
        # bug: Strava's raw CSV genuinely states local wall-clock time 2
        # hours earlier than Garmin's own startTimeLocal/startTimeGMT for
        # the identical ride) and duration sometimes differs by much more
        # than 60s too. avg_hr is identical down to the integer in every
        # case -- essentially impossible for two genuinely different rides.
        a = self._row(source="strava", sport="ride", avg_hr=157, duration_s=16874)
        b = self._row(
            source="garmin",
            sport="cycling",
            start_utc="2026-08-27T19:00:00Z",  # 2h after a's 17:00:00Z
            avg_hr=157,
            duration_s=9775,
        )
        assert _is_match(a, b) is True

    def test_matching_avg_hr_but_incompatible_sport_family_does_not_match(self) -> None:
        # The secondary tier still requires the sport-family gate -- an
        # exact avg_hr coincidence across two genuinely different sport
        # types (e.g. a run and a ride) should not be enough on its own.
        a = self._row(source="strava", sport="ride", avg_hr=150)
        b = self._row(source="garmin", sport="running", avg_hr=150)
        assert _is_match(a, b) is False

    def test_matching_avg_hr_outside_secondary_time_window_does_not_match(self) -> None:
        a = self._row(source="strava", sport="ride", avg_hr=150)
        b = self._row(
            source="garmin",
            sport="cycling",
            avg_hr=150,
            start_utc="2026-08-28T00:00:01Z",  # ~7h after a's 17:00:00Z
        )
        assert _is_match(a, b) is False

    def test_no_avg_hr_does_not_fall_back_to_secondary_tier(self) -> None:
        # Both None -- must not treat "no HR data on either side" as a match.
        a = self._row(source="strava", sport="ride", start_utc="2026-08-27T17:00:00Z")
        b = self._row(source="garmin", sport="cycling", start_utc="2026-08-27T19:00:00Z")
        assert _is_match(a, b) is False

    def test_avg_hr_off_by_one_still_matches(self) -> None:
        # Real pair, 2026-08-15: Strava 153bpm, Garmin 152bpm for the
        # identical ride -- each platform rounds its own computed average
        # slightly differently. Must still merge, not just exact equality.
        a = self._row(source="strava", sport="ride", avg_hr=153, start_utc="2026-08-27T17:00:00Z")
        b = self._row(
            source="garmin", sport="cycling", avg_hr=152, start_utc="2026-08-27T19:00:00Z"
        )
        assert _is_match(a, b) is True

    def test_avg_hr_off_by_two_does_not_match(self) -> None:
        a = self._row(source="strava", sport="ride", avg_hr=154, start_utc="2026-08-27T17:00:00Z")
        b = self._row(
            source="garmin", sport="cycling", avg_hr=152, start_utc="2026-08-27T19:00:00Z"
        )
        assert _is_match(a, b) is False

    def test_similar_avg_hr_five_hours_apart_does_not_match(self) -> None:
        # Real false-positive found in review, 2026-08-31: the original
        # secondary tier used a blanket 0-6h start-time window with no other
        # corroborating signal. Two genuinely distinct real rides ~5 hours
        # apart, both sitting at a similar Z2 heart rate (a realistic
        # scenario for this athlete's prescribed Z2 rides,
        # config/athlete.yaml: comp_prep's Saturday sessions), landed inside
        # that window and were silently merged, deleting a real session. The
        # tier now only matches a start-time offset close to the one
        # documented, confirmed-real 2-hour Strava/Garmin discrepancy, so
        # this must NOT match.
        a = self._row(source="strava", sport="ride", avg_hr=140, start_utc="2026-08-27T08:00:00Z")
        b = self._row(
            source="garmin", sport="cycling", avg_hr=141, start_utc="2026-08-27T13:00:00Z"
        )
        assert _is_match(a, b) is False


class TestDedupeActivities:
    def test_merges_real_duplicate_pattern(self, conn: sqlite3.Connection) -> None:
        # Mirrors the confirmed real case: Strava "workout" + Apple Health
        # "functional_strength_training", same start time, duration off by 1s.
        _insert(
            conn,
            source="strava",
            source_id="s1",
            sport="workout",
            start_utc="2026-02-20T07:00:00Z",
            duration_s=1800,
        )
        _insert(
            conn,
            source="apple_health",
            source_id="a1",
            sport="functional_strength_training",
            start_utc="2026-02-20T07:00:00Z",
            duration_s=1801,
        )

        result = dedupe_activities(conn)

        assert result.groups_merged == 1
        assert result.rows_deleted == 1
        remaining = conn.execute("SELECT * FROM activities").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["source"] == "strava"  # strava outranks apple_health
        merged_from = remaining[0]["merged_from"]
        assert '"source": "apple_health"' in merged_from
        assert '"source_id": "a1"' in merged_from

    def test_non_duplicates_untouched(self, conn: sqlite3.Connection) -> None:
        _insert(conn, source="strava", source_id="s1", local_date="2026-08-27")
        _insert(conn, source="apple_health", source_id="a1", local_date="2026-08-28")

        result = dedupe_activities(conn)

        assert result.groups_merged == 0
        assert result.rows_deleted == 0
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 2

    def test_garmin_outranks_strava_and_apple_health(self, conn: sqlite3.Connection) -> None:
        _insert(conn, source="apple_health", source_id="a1")
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="garmin", source_id="g1")  # inserted last, must still win

        result = dedupe_activities(conn)

        assert result.groups_merged == 1
        assert result.rows_deleted == 2
        remaining = conn.execute("SELECT * FROM activities").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["source"] == "garmin"

    def test_idempotent_second_run_is_a_noop(self, conn: sqlite3.Connection) -> None:
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="apple_health", source_id="a1")

        first = dedupe_activities(conn)
        second = dedupe_activities(conn)

        assert first.rows_deleted == 1
        assert second.groups_merged == 0
        assert second.rows_deleted == 0

    def test_transitive_merge_when_garmin_arrives_later(self, conn: sqlite3.Connection) -> None:
        # Strava absorbs Apple Health first (Garmin not loaded yet)...
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="apple_health", source_id="a1")
        dedupe_activities(conn)

        # ...then Garmin's backfill lands and matches the same session.
        _insert(conn, source="garmin", source_id="g1")
        result = dedupe_activities(conn)

        assert result.groups_merged == 1
        remaining = conn.execute("SELECT * FROM activities").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["source"] == "garmin"
        merged_from = remaining[0]["merged_from"]
        # Garmin's merged_from must carry both the strava row it directly
        # absorbed AND the apple_health row strava had already absorbed earlier.
        assert '"source": "strava"' in merged_from
        assert '"source": "apple_health"' in merged_from

    def test_reingested_loser_does_not_duplicate_merged_from_entry(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real bug found against production data (2026-08-27): re-running the
        # backfill re-ingests a source and resurrects an already-merged-away
        # row (expected, see module docstring). The next dedupe pass correctly
        # re-merges it -- but merged_from must not grow a second copy of the
        # same (source, source_id) pair just because it was merged twice.
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="apple_health", source_id="a1")
        dedupe_activities(conn)

        # Simulates re-ingestion resurrecting the deleted apple_health row.
        _insert(conn, source="apple_health", source_id="a1")
        dedupe_activities(conn)

        remaining = conn.execute("SELECT merged_from FROM activities").fetchall()
        assert len(remaining) == 1
        merged_from = json.loads(remaining[0]["merged_from"])
        assert merged_from == [{"source": "apple_health", "source_id": "a1"}]

    def test_custom_precedence_order(self, conn: sqlite3.Connection) -> None:
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="apple_health", source_id="a1")

        result = dedupe_activities(conn, precedence=("apple_health", "strava", "garmin"))

        remaining = conn.execute("SELECT * FROM activities").fetchall()
        assert remaining[0]["source"] == "apple_health"
        assert result.rows_deleted == 1

    def test_loser_referenced_by_activity_laps_is_skipped_not_crashed(
        self, conn: sqlite3.Connection
    ) -> None:
        # Real, latent gap found 2026-08-28: neither
        # bjj_sessions.linked_activity_id nor activity_laps.activity_id
        # declares ON DELETE CASCADE, so deleting a loser row that one of
        # them still references would violate a FK with foreign_keys=ON.
        # Forcing this via a custom precedence that makes the Apple Health
        # row (which has an attached lap here, an artificial setup purely to
        # exercise the FK path) the loser.
        garmin = _insert(conn, source="garmin", source_id="g1")
        apple = _insert(conn, source="apple_health", source_id="a1")
        # The lap is attached to the row that will be the LOSER under this
        # precedence (garmin outranked by apple_health here) -- that's what
        # makes the loser's DELETE hit the FK.
        conn.execute(
            "INSERT INTO activity_laps (activity_id, lap_index, start_utc) VALUES (?, 1, ?)",
            (garmin.activity_id, "2026-08-27T17:00:00Z"),
        )

        result = dedupe_activities(conn, precedence=("apple_health", "garmin"))

        # garmin (the loser under this precedence) should have been skipped,
        # not deleted -- both rows still present, and the skip is recorded,
        # not silently dropped.
        remaining_ids = {
            r["activity_id"] for r in conn.execute("SELECT activity_id FROM activities")
        }
        assert remaining_ids == {garmin.activity_id, apple.activity_id}
        assert result.rows_deleted == 0
        assert result.fk_conflicts == [garmin.activity_id]

    def test_merges_real_ride_timezone_discrepancy_pattern(self, conn: sqlite3.Connection) -> None:
        # End-to-end version of the real 2026-08-30 case above, through the
        # full dedupe_activities() pipeline, not just _is_match().
        _insert(
            conn,
            source="strava",
            source_id="18621999071",
            sport="ride",
            start_utc="2026-05-23T06:25:24Z",
            duration_s=16874,
            avg_hr=157,
        )
        _insert(
            conn,
            source="garmin",
            source_id="22983895320",
            sport="cycling",
            start_utc="2026-05-23T08:25:24Z",
            duration_s=9775,
            avg_hr=157,
        )

        result = dedupe_activities(conn)

        assert result.groups_merged == 1
        assert result.rows_deleted == 1
        remaining = conn.execute("SELECT * FROM activities").fetchall()
        assert len(remaining) == 1
        assert remaining[0]["source"] == "garmin"  # garmin outranks strava

    def test_does_not_merge_distinct_rides_five_hours_apart_with_similar_hr(
        self, conn: sqlite3.Connection
    ) -> None:
        # End-to-end version of the false-positive case above, through the
        # full dedupe_activities() pipeline -- two real, distinct rides must
        # both survive.
        _insert(
            conn,
            source="strava",
            source_id="ride1",
            sport="ride",
            start_utc="2026-08-27T08:00:00Z",
            duration_s=3600,
            avg_hr=140,
        )
        _insert(
            conn,
            source="garmin",
            source_id="ride2",
            sport="cycling",
            start_utc="2026-08-27T13:00:00Z",
            duration_s=3600,
            avg_hr=141,
        )

        result = dedupe_activities(conn)

        assert result.groups_merged == 0
        assert result.rows_deleted == 0
        assert conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 2

    def test_fk_conflicts_empty_when_no_conflict(self, conn: sqlite3.Connection) -> None:
        _insert(conn, source="strava", source_id="s1")
        _insert(conn, source="apple_health", source_id="a1")
        result = dedupe_activities(conn)
        assert result.fk_conflicts == []
