-- Migration 0011: allow 'strength_c' and 'yoga_flow' calisthenics sessions.
--
-- 2026-10-21: Francisco's week moved to 3 strength sessions (A Monday,
-- B Wednesday, C Saturday) plus 2 standalone strength-yoga flow sessions, so
-- both need to be loggable. SQLite can't ALTER a CHECK constraint, so the
-- table is rebuilt with the same columns and every existing row copied over
-- unchanged (ids and timestamps included). No other table references it.
CREATE TABLE calisthenics_sessions_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL,
    session_type   TEXT NOT NULL CHECK (
        session_type IN ('strength_a', 'strength_b', 'strength_c', 'yoga_flow')
    ),
    session_rpe    INTEGER CHECK (session_rpe BETWEEN 1 AND 10),
    exercises_json TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    duration_min   INTEGER CHECK (duration_min > 0),
    computed_load  REAL,
    UNIQUE (date, session_type)
);
INSERT INTO calisthenics_sessions_new
    (id, date, session_type, session_rpe, exercises_json, notes,
     created_at, updated_at, duration_min, computed_load)
SELECT id, date, session_type, session_rpe, exercises_json, notes,
       created_at, updated_at, duration_min, computed_load
FROM calisthenics_sessions;
DROP TABLE calisthenics_sessions;
ALTER TABLE calisthenics_sessions_new RENAME TO calisthenics_sessions;
