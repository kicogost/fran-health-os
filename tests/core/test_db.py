from __future__ import annotations

import json
import sqlite3
import time

import pytest

from health_os.core import db as db_module

EXPECTED_TABLES = {
    "schema_migrations",
    "daily_metrics",
    "activities",
    "bjj_sessions",
    "calisthenics_sessions",
    "subjective_log",
    "body_measurements",
    "activity_laps",
    "derived_daily",
    "ingest_runs",
}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


class TestMigrations:
    def test_creates_all_expected_tables(self, conn: sqlite3.Connection) -> None:
        assert _table_names(conn) >= EXPECTED_TABLES

    def test_records_applied_version(self, conn: sqlite3.Connection) -> None:
        versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations")]
        assert versions == [1, 2, 3, 4]

    def test_is_idempotent(self, conn: sqlite3.Connection) -> None:
        newly_applied = db_module.apply_migrations(conn)
        assert newly_applied == []

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


class TestMigrationAtomicity:
    """Real bug found 2026-08-28, confirmed by direct reproduction:
    `conn.executescript()` does NOT run a multi-statement migration file as
    one rollback-able transaction on its own -- each DDL statement ran in
    SQLite's own autocommit mode, so a failure partway through a script left
    earlier statements permanently applied but never recorded in
    `schema_migrations`, wedging every future `apply_migrations()` call
    (it would retry the same broken script and fail again on the very first,
    already-applied statement). Fixed by prepending a literal `BEGIN;` to the
    script text and managing commit/rollback explicitly in Python.
    """

    def _write_migration(self, migrations_dir, name: str, sql: str) -> None:
        (migrations_dir / name).write_text(sql)

    def test_failing_multi_statement_migration_leaves_no_partial_state(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(db_module, "MIGRATIONS_DIR", tmp_path)
        self._write_migration(
            tmp_path,
            "0001_broken.sql",
            "CREATE TABLE t1 (id INTEGER);\n"
            "CREATE TABLE t2 (id INTEGER);\n"
            "CREATE TABLE t1 (id INTEGER);\n",  # duplicate -- fails
        )
        conn = db_module.connect(":memory:")
        try:
            with pytest.raises(sqlite3.OperationalError):
                db_module.apply_migrations(conn)

            # Neither t1 nor t2 should have survived the failed script.
            tables = {
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('t1', 't2')"
                )
            }
            assert tables == set()
            versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
            assert versions == []
        finally:
            conn.close()

    def test_retry_after_fixing_a_failed_migration_applies_cleanly(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(db_module, "MIGRATIONS_DIR", tmp_path)
        self._write_migration(
            tmp_path,
            "0001_broken.sql",
            "CREATE TABLE t3 (id INTEGER);\nCREATE TABLE t3 (id INTEGER);\n",
        )
        conn = db_module.connect(":memory:")
        try:
            with pytest.raises(sqlite3.OperationalError):
                db_module.apply_migrations(conn)

            # Fix the file (same version, corrected content) and retry --
            # must succeed cleanly with no leftover corruption from the
            # earlier failed attempt.
            self._write_migration(tmp_path, "0001_broken.sql", "CREATE TABLE t3 (id INTEGER);\n")
            applied = db_module.apply_migrations(conn)
            assert applied == [1]
            assert (
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 't3'"
                ).fetchone()
                is not None
            )
            assert [
                r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
            ] == [1]
        finally:
            conn.close()

    def test_successful_migration_and_schema_migrations_row_commit_together(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(db_module, "MIGRATIONS_DIR", tmp_path)
        self._write_migration(tmp_path, "0001_good.sql", "CREATE TABLE t4 (id INTEGER);\n")
        conn = db_module.connect(":memory:")
        try:
            applied = db_module.apply_migrations(conn)
            assert applied == [1]
            assert (
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 't4'"
                ).fetchone()
                is not None
            )
            assert [
                r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
            ] == [1]
        finally:
            conn.close()


class TestResolveDbPath:
    def test_explicit_arg_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HEALTH_OS_DB_PATH", "env/path.db")
        assert db_module.resolve_db_path("explicit.db") == db_module.Path("explicit.db")

    def test_env_var_used_when_no_arg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HEALTH_OS_DB_PATH", "env/path.db")
        assert db_module.resolve_db_path() == db_module.Path("env/path.db")

    def test_default_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HEALTH_OS_DB_PATH", raising=False)
        assert db_module.resolve_db_path() == db_module.DEFAULT_DB_PATH


class TestUpsert:
    def test_insert_new_row(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.45}, ["date"]
        )
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)).fetchone()
        assert row["weight_kg"] == 78.45
        assert row["created_at"] is not None
        assert row["updated_at"] is not None

    def test_conflict_updates_not_duplicates(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.45}, ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.30}, ["date"]
        )
        rows = conn.execute(
            "SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["weight_kg"] == 78.30

    def test_partial_upsert_does_not_clobber_other_columns(self, conn: sqlite3.Connection) -> None:
        # Simulates two separate ingestion runs for the same date: Garmin fills in
        # resting_hr first, Apple Health/Renpho fills in weight_kg later. Neither
        # should erase the other's value.
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "resting_hr": 52.0}, ["date"]
        )
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.45}, ["date"]
        )
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)).fetchone()
        assert row["resting_hr"] == 52.0
        assert row["weight_kg"] == 78.45

    def test_partial_upsert_without_merge_clobbers_sources_real_bug(
        self, conn: sqlite3.Connection
    ) -> None:
        # Documents the bug this fixes (found 2026-08-28, confirmed by two
        # independent reviewers): without merge_json_columns, a second
        # ingestion run's `sources` dict REPLACES the first's wholesale, even
        # though the underlying VALUE columns are correctly preserved above.
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "resting_hr": 52.0, "sources": {"resting_hr": "garmin"}},
            ["date"],
        )
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "weight_kg": 78.45, "sources": {"weight_kg": "apple_health"}},
            ["date"],
        )
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)).fetchone()
        assert row["resting_hr"] == 52.0  # value survives
        assert json.loads(row["sources"]) == {"weight_kg": "apple_health"}  # provenance lost

    def test_merge_json_columns_preserves_provenance_across_partial_upserts(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "resting_hr": 52.0, "sources": {"resting_hr": "garmin"}},
            ["date"],
            merge_json_columns=["sources"],
        )
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "weight_kg": 78.45, "sources": {"weight_kg": "apple_health"}},
            ["date"],
            merge_json_columns=["sources"],
        )
        row = conn.execute("SELECT * FROM daily_metrics WHERE date = ?", ("2026-08-27",)).fetchone()
        assert row["resting_hr"] == 52.0
        assert row["weight_kg"] == 78.45
        assert json.loads(row["sources"]) == {"resting_hr": "garmin", "weight_kg": "apple_health"}

    def test_merge_json_columns_new_value_wins_on_key_conflict(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "sources": {"resting_hr": "garmin"}},
            ["date"],
            merge_json_columns=["sources"],
        )
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "sources": {"resting_hr": "corrected_manually"}},
            ["date"],
            merge_json_columns=["sources"],
        )
        row = conn.execute(
            "SELECT sources FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        assert json.loads(row["sources"]) == {"resting_hr": "corrected_manually"}

    def test_merge_json_columns_on_fresh_insert_needs_no_existing_row(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "sources": {"resting_hr": "garmin"}},
            ["date"],
            merge_json_columns=["sources"],
        )
        row = conn.execute(
            "SELECT sources FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        assert json.loads(row["sources"]) == {"resting_hr": "garmin"}

    def test_conflict_bumps_updated_at_but_not_created_at(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.45}, ["date"]
        )
        first = conn.execute(
            "SELECT created_at, updated_at FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        time.sleep(0.01)
        db_module.upsert(
            conn, "daily_metrics", {"date": "2026-08-27", "weight_kg": 78.30}, ["date"]
        )
        second = conn.execute(
            "SELECT created_at, updated_at FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchone()
        assert second["created_at"] == first["created_at"]
        assert second["updated_at"] > first["updated_at"]

    def test_dict_and_list_values_json_encoded(self, conn: sqlite3.Connection) -> None:
        db_module.upsert(
            conn,
            "daily_metrics",
            {"date": "2026-08-27", "sources": {"weight_kg": "apple_health:renpho"}},
            ["date"],
        )
        raw = conn.execute(
            "SELECT sources FROM daily_metrics WHERE date = ?", ("2026-08-27",)
        ).fetchone()["sources"]
        assert raw == '{"weight_kg": "apple_health:renpho"}'

    def test_touch_column_none_for_tables_without_updated_at(
        self, conn: sqlite3.Connection
    ) -> None:
        db_module.upsert(
            conn,
            "derived_daily",
            {"date": "2026-08-27", "metric_name": "hrv_baseline_status", "value": 1.0},
            ["date", "metric_name"],
            touch_column=None,
        )
        row = conn.execute(
            "SELECT * FROM derived_daily WHERE date = ? AND metric_name = ?",
            ("2026-08-27", "hrv_baseline_status"),
        ).fetchone()
        assert row["value"] == 1.0

    def test_rejects_unsafe_identifier(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            db_module.upsert(
                conn, "daily_metrics; DROP TABLE daily_metrics", {"date": "x"}, ["date"]
            )

    def test_rejects_empty_row(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(ValueError):
            db_module.upsert(conn, "daily_metrics", {}, ["date"])


class TestNaturalKeyConstraints:
    def test_activities_unique_on_source_and_source_id(self, conn: sqlite3.Connection) -> None:
        row = {
            "activity_id": "garmin:123",
            "source": "garmin",
            "source_id": "123",
            "start_utc": "2026-08-27T17:00:00Z",
            "local_date": "2026-08-27",
        }
        conn.execute(
            "INSERT INTO activities (activity_id, source, source_id, start_utc, local_date) "
            "VALUES (:activity_id, :source, :source_id, :start_utc, :local_date)",
            row,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO activities (activity_id, source, source_id, start_utc, local_date) "
                "VALUES ('garmin:123-dup', :source, :source_id, :start_utc, :local_date)",
                row,
            )

    def test_bjj_sessions_unique_on_date_and_type(self, conn: sqlite3.Connection) -> None:
        row = {"date": "2026-08-27", "session_type": "class", "duration_min": 90, "session_rpe": 7}
        conn.execute(
            "INSERT INTO bjj_sessions (date, session_type, duration_min, session_rpe) "
            "VALUES (:date, :session_type, :duration_min, :session_rpe)",
            row,
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bjj_sessions (date, session_type, duration_min, session_rpe) "
                "VALUES (:date, :session_type, :duration_min, :session_rpe)",
                row,
            )

    def test_bjj_sessions_rejects_out_of_range_rpe(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bjj_sessions (date, session_type, duration_min, session_rpe) "
                "VALUES ('2026-08-27', 'class', 90, 11)"
            )

    def test_bjj_sessions_rejects_invalid_session_type(self, conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO bjj_sessions (date, session_type, duration_min, session_rpe) "
                "VALUES ('2026-08-27', 'sparring', 90, 7)"
            )


class TestIngestRuns:
    def test_start_and_finish_success(self, conn: sqlite3.Connection) -> None:
        run_id = db_module.start_ingest_run(conn, "garmin")
        row = conn.execute("SELECT * FROM ingest_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "running"
        assert row["finished_at"] is None

        db_module.finish_ingest_run(
            conn, run_id, status="success", rows_in=10, rows_upserted=9, rows_skipped=1
        )
        row = conn.execute("SELECT * FROM ingest_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["status"] == "success"
        assert row["finished_at"] is not None
        assert row["rows_in"] == 10
        assert row["rows_upserted"] == 9
        assert row["rows_skipped"] == 1

    def test_finish_with_errors_encoded_as_json(self, conn: sqlite3.Connection) -> None:
        run_id = db_module.start_ingest_run(conn, "strava")
        db_module.finish_ingest_run(
            conn, run_id, status="failed", errors=["rate limited", "timeout"]
        )
        row = conn.execute("SELECT errors FROM ingest_runs WHERE id = ?", (run_id,)).fetchone()
        assert row["errors"] == '["rate limited", "timeout"]'

    def test_rejects_invalid_status(self, conn: sqlite3.Connection) -> None:
        run_id = db_module.start_ingest_run(conn, "garmin")
        with pytest.raises(ValueError):
            db_module.finish_ingest_run(conn, run_id, status="done")

    def test_rejects_unknown_run_id_instead_of_silent_no_op(self, conn: sqlite3.Connection) -> None:
        # Real gap found 2026-08-28: an UPDATE ... WHERE id = ? that matches
        # no row used to silently succeed, in a table whose whole purpose is
        # being the audit trail for noticing a silently-broken pipeline.
        with pytest.raises(ValueError, match="no ingest_runs row"):
            db_module.finish_ingest_run(conn, 999999, status="success")
