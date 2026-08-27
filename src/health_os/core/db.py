"""Connection, migration, and upsert helpers for the canonical SQLite store.

This module is the only place that should ever open `data/health.db` directly.
Everything else — ingestion, metrics, coaching, dashboard — goes through `init_db()`
and the helpers here, so idempotent-upsert behaviour (design principle 4) and the
migration history stay in one place.

No network calls here, and none of this is Garmin/Strava/Apple-Health-specific —
that's Phase 2+.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_PACKAGE_ROOT = Path(__file__).resolve().parent
MIGRATIONS_DIR = _PACKAGE_ROOT / "migrations"
DEFAULT_DB_PATH = Path("data/health.db")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MIGRATION_FILENAME_RE = re.compile(r"^(\d{4})_.+\.sql$")


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Resolve the database file path.

    Precedence: an explicit `db_path` argument, then the `HEALTH_OS_DB_PATH` env var
    (see .env.example), then the default `data/health.db` relative to the current
    working directory.
    """
    if db_path is not None:
        return Path(db_path)
    env_path = os.environ.get("HEALTH_OS_DB_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection to the canonical store, with sane pragmas set.

    Does not apply migrations — use `init_db()` for that. Creates the parent
    directory if it doesn't exist yet (the db file itself is created by sqlite3 on
    first write), but never touches anything under `data/raw/` — this only ever
    opens the one canonical `.db` file.
    """
    path = resolve_db_path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _pending_migrations(conn: sqlite3.Connection) -> list[tuple[int, Path]]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY,
            filename   TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}

    found: list[tuple[int, Path]] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _MIGRATION_FILENAME_RE.match(path.name)
        if not match:
            raise ValueError(f"migration filename {path.name!r} doesn't match NNNN_description.sql")
        found.append((int(match.group(1)), path))

    pending = [(version, path) for version, path in found if version not in applied]
    pending.sort(key=lambda item: item[0])
    return pending


def apply_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply any migrations not yet recorded in `schema_migrations`, in order.

    Each migration runs in its own transaction: either it and its
    `schema_migrations` row both commit, or neither does. Returns the list of
    newly-applied version numbers (empty if the schema was already current).
    """
    applied_versions: list[int] = []
    for version, path in _pending_migrations(conn):
        sql = path.read_text()
        with conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, filename) VALUES (?, ?)",
                (version, path.name),
            )
        applied_versions.append(version)
    return applied_versions


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection and bring the schema up to date. The main entry point."""
    conn = connect(db_path)
    apply_migrations(conn)
    return conn


def _check_identifier(name: str, *, what: str) -> None:
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"unsafe {what} name: {name!r}")


def upsert(
    conn: sqlite3.Connection,
    table: str,
    row: Mapping[str, Any],
    conflict_columns: Sequence[str],
    *,
    touch_column: str | None = "updated_at",
) -> None:
    """Idempotent insert-or-update on a natural key (design principle 4).

    `row` values that are `dict`/`list` are JSON-encoded automatically (used for
    columns like `daily_metrics.sources`, `activities.merged_from`,
    `derived_daily.inputs_json`). On conflict with `conflict_columns`, every other
    column present in `row` is overwritten — never blindly inserted as a duplicate.

    `touch_column`, if set and not already present in `row` or `conflict_columns`,
    is bumped to the current UTC timestamp on both insert and update. Pass
    `touch_column=None` for tables with no such bookkeeping column (e.g.
    `ingest_runs`, which uses its own start/finish helpers instead).
    """
    if not row:
        raise ValueError("upsert() called with an empty row")
    _check_identifier(table, what="table")
    for col in row:
        _check_identifier(col, what="column")
    for col in conflict_columns:
        _check_identifier(col, what="conflict column")

    encoded: dict[str, Any] = {
        col: json.dumps(val) if isinstance(val, (dict, list)) else val for col, val in row.items()
    }

    columns = list(encoded.keys())
    placeholders = ", ".join(f":{col}" for col in columns)
    column_list = ", ".join(columns)

    update_columns = [col for col in columns if col not in conflict_columns]
    set_parts = [f"{col} = excluded.{col}" for col in update_columns]
    if touch_column and touch_column not in encoded and touch_column not in conflict_columns:
        _check_identifier(touch_column, what="touch column")
        set_parts.append(f"{touch_column} = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')")
    if not set_parts:
        # Nothing to update but the conflict key itself — DO UPDATE SET still needs
        # at least one assignment, so make it a no-op rather than a special case.
        set_parts.append(f"{conflict_columns[0]} = excluded.{conflict_columns[0]}")
    set_clause = ", ".join(set_parts)

    conflict_target = ", ".join(conflict_columns)
    sql = (
        f"INSERT INTO {table} ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_target}) DO UPDATE SET {set_clause}"
    )
    with conn:
        conn.execute(sql, encoded)


def start_ingest_run(conn: sqlite3.Connection, source: str) -> int:
    """Record the start of an ingestion run; returns its `ingest_runs.id`."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO ingest_runs (source, started_at, status)
            VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'running')
            """,
            (source,),
        )
    return int(cursor.lastrowid)


def finish_ingest_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    rows_in: int | None = None,
    rows_upserted: int | None = None,
    rows_skipped: int | None = None,
    errors: list[str] | None = None,
) -> None:
    """Record the outcome of an ingestion run started with `start_ingest_run()`."""
    if status not in ("success", "failed"):
        raise ValueError(f"status must be 'success' or 'failed', got {status!r}")
    with conn:
        conn.execute(
            """
            UPDATE ingest_runs
            SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                status = :status,
                rows_in = :rows_in,
                rows_upserted = :rows_upserted,
                rows_skipped = :rows_skipped,
                errors = :errors
            WHERE id = :run_id
            """,
            {
                "status": status,
                "rows_in": rows_in,
                "rows_upserted": rows_upserted,
                "rows_skipped": rows_skipped,
                "errors": json.dumps(errors) if errors is not None else None,
                "run_id": run_id,
            },
        )
