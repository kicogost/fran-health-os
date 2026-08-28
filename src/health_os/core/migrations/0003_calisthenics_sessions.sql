-- Migration 0003: calisthenics session log.
--
-- Closes a real, repeatedly-flagged gap: calisthenics (the Monday/Wednesday
-- strength_a/strength_b sessions in config/athlete.yaml: comp_prep.
-- strength_sessions) had no logging mechanism anywhere in this codebase --
-- the Training dashboard page and the weekly retro both explicitly said so
-- rather than inventing data. Francisco asked directly (2026-08-28) how to
-- track it.
--
-- Split, same pattern as BJJ (Garmin captures physiology, the manual log
-- captures what Garmin can't see): recording calisthenics as a Garmin
-- "Strength Training" activity needs zero new code (already flows through
-- the existing activities pipeline) and gives duration/HR/calories. This
-- table is for the exercise-level detail Garmin's activity summary doesn't
-- have -- sets/reps/added weight per exercise, the actual progression
-- signal. `exercises_json` is a JSON list of
-- {exercise, sets, reps, added_weight_kg, notes} -- one entry per exercise
-- actually done that session (not necessarily every exercise
-- config/athlete.yaml prescribes, if one got cut) -- structured enough to
-- chart per-exercise trends later without a full normalized child table for
-- what is, for now, a short fixed list of ~5-6 exercises per session type.
CREATE TABLE IF NOT EXISTS calisthenics_sessions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL,
    session_type  TEXT NOT NULL CHECK (session_type IN ('strength_a', 'strength_b')),
    session_rpe   INTEGER CHECK (session_rpe BETWEEN 1 AND 10),
    exercises_json TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (date, session_type)
);
