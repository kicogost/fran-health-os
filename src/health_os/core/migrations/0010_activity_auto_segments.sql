-- Migration 0010: auto-detected round/rest segments for un-lapped BJJ activities.
--
-- Francisco's stated recording preference (2026-09-29): fixed 5min rounds +
-- 60s rest, and he doesn't want to press a lap button while he's sparring
-- and focused on that. `metrics/bjj_laps.py: auto_detect_rounds()` locates
-- that known cadence directly in a BJJ activity's raw heart-rate stream
-- (fetched via `ingest/garmin.py: fetch_activity_hr_stream()`) for any
-- activity that has NO real manually-pressed laps (or only lap 1, the
-- drilling lap) -- see `ingest/live_sync.py`'s BJJ block for the exact
-- trigger condition.
--
-- Deliberately a SEPARATE table from `activity_laps`, not a second kind of
-- row mixed into it: `activity_laps`'s own docstring/migration 0004 comment
-- is explicit that it holds ONLY what Garmin's `get_activity_splits()`
-- actually reports (raw vs. derived stays separate, design principle 6) --
-- these rows are OUR interpretation of a raw HR stream, not anything Garmin
-- told us, so blending them into that table would make a real Garmin lap
-- and a guessed one indistinguishable. `label` is stored directly here
-- (unlike `activity_laps`, which never stores a sparring/rest label) since
-- the auto-detector already KNOWS which phase each segment is by
-- construction (round vs. rest vs. the leading warmup/drilling block) --
-- there's no `classify_bjj_laps()`-style self-relative-median guess to make
-- after the fact.
CREATE TABLE IF NOT EXISTS activity_auto_segments (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id    TEXT NOT NULL REFERENCES activities (activity_id),
    segment_index  INTEGER NOT NULL,
    start_s        REAL NOT NULL,   -- seconds elapsed since activity start
    end_s          REAL NOT NULL,
    label          TEXT NOT NULL CHECK (label IN ('warmup_or_drilling', 'round', 'rest')),
    avg_hr         REAL,
    max_hr         REAL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (activity_id, segment_index)
);
