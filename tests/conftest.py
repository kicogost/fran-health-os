from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from health_os.core import db as db_module


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """A fresh, fully-migrated in-memory database for each test."""
    connection = db_module.connect(":memory:")
    db_module.apply_migrations(connection)
    yield connection
    connection.close()
