from __future__ import annotations

import sqlite3
import time

import pytest

from health_os.core import db as db_module

EXPECTED_TABLES = {
    "schema_migrations",
    "daily_metrics",
    "activities",
    "bjj_sessions",
    "subjective_log",
    "body_measurements",
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
        assert versions == [1, 2, 3]

    def test_is_idempotent(self, conn: sqlite3.Connection) -> None:
        newly_applied = db_module.apply_migrations(conn)
        assert newly_applied == []

    def test_foreign_keys_enabled(self, conn: sqlite3.Connection) -> None:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


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
