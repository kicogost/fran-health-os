"""Guards against core/schema.sql drifting from core/migrations/.

schema.sql is a human-readable snapshot, not what gets executed — see its header
comment. This test applies both the real migrations and schema.sql to separate
fresh databases and asserts they produce an identical set of schema objects.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from health_os.core import db as db_module

SCHEMA_SQL_PATH = Path(db_module.__file__).parent / "schema.sql"

_IGNORED_TABLES = {"schema_migrations", "sqlite_sequence"}


def _schema_objects(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL"
    ).fetchall()
    return {
        (row["type"], row["name"], row["sql"]) for row in rows if row["name"] not in _IGNORED_TABLES
    }


def test_schema_sql_matches_applied_migrations() -> None:
    migrated = db_module.connect(":memory:")
    db_module.apply_migrations(migrated)

    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    snapshot.executescript(SCHEMA_SQL_PATH.read_text())

    try:
        assert _schema_objects(migrated) == _schema_objects(snapshot), (
            "core/schema.sql has drifted from core/migrations/ — update the snapshot "
            "to match, or add a new numbered migration instead of editing 0001 in place."
        )
    finally:
        migrated.close()
        snapshot.close()
