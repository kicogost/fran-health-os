-- Migration 0004: per-lap detail for activities (round-by-round BJJ tracking).
--
-- Francisco's real recording plan (verified 2026-08-28 against a real Garmin
-- test activity + client.get_activity_splits()): lap 1 = drilling, then a new
-- lap at the start of each sparring round (work + rest together) or a full
-- rest round, intending to distinguish "sparring" from "rest" laps after the
-- fact by HR level -- Garmin itself doesn't classify freeform manually-lapped
-- intervals this way (no reliable intensityType signal for this recording
-- style, confirmed against the real response), so that classification has to
-- happen in our own code (metrics/bjj_laps.py), not at ingestion. This table
-- stores the raw laps only -- design principle 6, raw vs. derived stays
-- separate, same as daily_metrics vs. derived_daily.
CREATE TABLE IF NOT EXISTS activity_laps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id   TEXT NOT NULL REFERENCES activities (activity_id),
    lap_index     INTEGER NOT NULL,
    start_utc     TEXT NOT NULL,
    duration_s    REAL,
    distance_m    REAL,
    avg_hr        INTEGER,
    max_hr        INTEGER,
    calories      REAL,
    intensity_type TEXT,           -- raw Garmin value, e.g. "ACTIVE" -- not a classification
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (activity_id, lap_index)
);
