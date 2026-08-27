"""Guards against core/schema.sql drifting from core/migrations/.

schema.sql is a human-readable snapshot, not what gets executed — see its header
comment. Deliberately a SEMANTIC comparison (columns: name/type/notnull/pk/default
per table), not literal SQL text: `ALTER TABLE ... ADD/DROP COLUMN` rewrites a
table's stored CREATE TABLE text with columns appended in an ugly, hard-to-read
order (verified directly: see migration 0002's actual sqlite_master.sql output).
A literal-text version of this test would force schema.sql into that same ugly
shape forever the moment any migration alters an existing table rather than
creating a new one — defeating schema.sql's entire purpose as a *readable*
snapshot.

Known gap: this does not verify CHECK constraint expressions match (SQLite has
no clean introspection pragma for them) — covered instead by the constraint-
enforcement tests in test_db.py (e.g. rejecting an out-of-range session_rpe).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from health_os.core import db as db_module

SCHEMA_SQL_PATH = Path(db_module.__file__).parent / "schema.sql"

_IGNORED_TABLES = {"schema_migrations", "sqlite_sequence"}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows if row["name"] not in _IGNORED_TABLES}


def _columns(conn: sqlite3.Connection, table: str) -> set[tuple]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    # (name, type, notnull, default, pk). `cid` (ordinal position) is deliberately
    # excluded: ALTER TABLE always appends new columns at the end, so position
    # isn't meaningful to compare between a migrated table and a freshly
    # hand-ordered one in schema.sql.
    return {(r["name"], r["type"], r["notnull"], r["dflt_value"], r["pk"]) for r in rows}


def test_schema_sql_matches_applied_migrations() -> None:
    migrated = db_module.connect(":memory:")
    db_module.apply_migrations(migrated)

    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    snapshot.executescript(SCHEMA_SQL_PATH.read_text())

    try:
        assert _table_names(migrated) == _table_names(snapshot), (
            "core/schema.sql has a different set of tables than core/migrations/ produces."
        )
        for table in _table_names(migrated):
            assert _columns(migrated, table) == _columns(snapshot, table), (
                f"{table}: core/schema.sql has drifted from core/migrations/ — update the "
                "snapshot to match, or add a new numbered migration instead of editing an "
                "already-applied one in place."
            )
    finally:
        migrated.close()
        snapshot.close()
