-- Health OS canonical schema — human-readable snapshot.
--
-- This is NOT what db.py executes. The source of truth is the ordered migration
-- files in core/migrations/ (applied by db.apply_migrations, tracked in the
-- schema_migrations table). This file is a snapshot of the schema those migrations
-- produce, kept here purely for readability — "what does the DB look like right now"
-- without reading every migration in sequence. tests/core/test_schema_sync.py fails
-- if this drifts from the migrations.
--
-- Current version: 3 (core/migrations/0001_initial_schema.sql,
-- core/migrations/0002_bjj_wellness_and_load.sql,
-- core/migrations/0003_calisthenics_sessions.sql)
--
-- Note: this snapshot is semantically compared against the migrated schema
-- (column name/type/notnull/pk/default per table), not byte-for-byte SQL text —
-- ALTER TABLE ADD/DROP COLUMN rewrites a table's stored CREATE TABLE text with
-- new columns appended in an ugly, hard-to-read order, so this file's column
-- ordering is deliberately hand-arranged for readability instead. See
-- tests/core/test_schema_sync.py for exactly what's (and isn't) verified.

PRAGMA foreign_keys = ON;

-- One row per calendar date (Europe/Madrid local date). Wellness/wearable metrics.
-- Design principle 6: missing = NULL, never invented/interpolated.
-- Design principle 9: `sources` records which source populated which field, as JSON
-- (e.g. {"weight_kg": "apple_health:renpho", "resting_hr": "garmin"}), so every value
-- is traceable to where it came from. Weight specifically follows its own precedence
-- (Apple Health / Renpho is authoritative, not the general Garmin > Strava > Apple
-- Health rule in design principle 5 — Garmin has no scale on this hardware) — see
-- CLAUDE.md "chest strap purchase confirmed" note for the equivalent BJJ-side decision.
CREATE TABLE IF NOT EXISTS daily_metrics (
    date                TEXT PRIMARY KEY,      -- ISO 'YYYY-MM-DD', Europe/Madrid local date
    weight_kg           REAL,
    resting_hr          REAL,
    hrv_overnight_ms    REAL,
    hrv_status          TEXT,                  -- Garmin's own status label, verbatim
    sleep_total_min     INTEGER,
    sleep_deep_min      INTEGER,
    sleep_rem_min       INTEGER,
    sleep_light_min     INTEGER,
    sleep_awake_min     INTEGER,
    sleep_score         INTEGER,
    body_battery_max    INTEGER,
    body_battery_min    INTEGER,
    stress_avg          INTEGER,
    steps               INTEGER,
    active_kcal         INTEGER,
    total_kcal          INTEGER,
    vo2max              REAL,
    training_readiness  INTEGER,               -- Garmin's own; our computed readiness lives in derived_daily
    respiration_avg     REAL,
    spo2_avg            REAL,
    skin_temp_delta     REAL,
    sources             TEXT,                  -- JSON: {"<column>": "<source>[:<detail>]"}
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One row per training session, any source. Design principle 5: (source, source_id)
-- is the natural key; merged_from records which other source rows were superseded by
-- this one during dedup (Phase 3), so every merge decision stays auditable.
CREATE TABLE IF NOT EXISTS activities (
    activity_id      TEXT PRIMARY KEY,         -- synthesized: "<source>:<source_id>"
    source           TEXT NOT NULL,            -- garmin | strava | apple_health | manual
    source_id        TEXT NOT NULL,            -- source's native activity id
    start_utc        TEXT NOT NULL,            -- ISO8601 UTC
    local_date       TEXT NOT NULL,            -- Europe/Madrid calendar date attribution
    sport            TEXT,
    sub_sport        TEXT,
    duration_s       INTEGER,
    distance_m       REAL,
    avg_hr           INTEGER,
    max_hr           INTEGER,
    hr_zone_1_s      INTEGER,
    hr_zone_2_s      INTEGER,
    hr_zone_3_s      INTEGER,
    hr_zone_4_s      INTEGER,
    hr_zone_5_s      INTEGER,
    training_load    REAL,
    aerobic_te       REAL,
    anaerobic_te     REAL,
    avg_power        REAL,
    elevation_gain_m REAL,
    perceived_rpe    INTEGER,
    merged_from      TEXT,                     -- JSON array of superseded {"source":...,"source_id":...} rows
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_activities_local_date ON activities (local_date);

-- Manual BJJ log — first-class ingestion path (kickoff doc section 2.4), not an
-- afterthought. `linked_activity_id` points at the chest-strap-recorded Garmin
-- activity for the same class once that hardware is in use (ADR 0002) — linked, not
-- deduplicated against it; see docs/bjj_recording_workflow.md.
-- `rounds_gassed` (a count, not a bool — added migration 0002) and
-- `session_feeling` (dizzy < gassed < tired < okay, worst to best) are the
-- athlete's own three BJJ-specific tracking questions; `dizzy` is a genuine
-- safety signal, not just "very tired", given the injury/safety-rail history
-- already encoded elsewhere in this project.
CREATE TABLE IF NOT EXISTS bjj_sessions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    date               TEXT NOT NULL,
    session_type       TEXT NOT NULL CHECK (session_type IN ('class', 'open_mat', 'gi_drilling')),
    duration_min       INTEGER NOT NULL,
    rounds_rolled      INTEGER,
    rounds_gassed      INTEGER,
    session_feeling    TEXT CHECK (session_feeling IN ('dizzy', 'gassed', 'tired', 'okay')),
    session_rpe        INTEGER NOT NULL CHECK (session_rpe BETWEEN 1 AND 10),
    niggles            TEXT,
    notes              TEXT,
    computed_load      REAL,                   -- Foster's method: duration_min * session_rpe
    linked_activity_id TEXT REFERENCES activities (activity_id),
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (date, session_type)
);

-- Manual calisthenics log — added migration 0003, closing a real gap: Garmin's
-- "Strength Training" activity type (recording calisthenics that way needs no new
-- ingestion code) gives duration/HR/calories, but never exercise-level detail.
-- `exercises_json` is a JSON list of {exercise, sets, reps, added_weight_kg, notes},
-- one entry per exercise actually done — checked against config/athlete.yaml:
-- comp_prep.strength_sessions's prescribed list, but sessions may deviate from it.
CREATE TABLE IF NOT EXISTS calisthenics_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL,
    session_type   TEXT NOT NULL CHECK (session_type IN ('strength_a', 'strength_b')),
    session_rpe    INTEGER CHECK (session_rpe BETWEEN 1 AND 10),
    exercises_json TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (date, session_type)
);

-- One row per date: subjective/qualitative input. `social_meal` is the known deficit
-- disruptor (config/athlete.yaml: nutrition.social_meal_policy) — correlated against
-- the weight trend once the correlation engine lands.
-- `sleep_quality`/`stress`/`fatigue`/`muscle_soreness` (added migration 0002) are a
-- Hooper-Mackinnon-inspired daily wellness questionnaire — all four use the SAME
-- polarity (1 = best, 10 = worst) so they sum cleanly into `hooper_index`
-- (4 = excellent, 40 = terrible), computed by core.models.SubjectiveLogEntry, same
-- pattern as bjj_sessions.computed_load — never entered by hand.
CREATE TABLE IF NOT EXISTS subjective_log (
    date            TEXT PRIMARY KEY,
    felt_note       TEXT,
    protein_hit     INTEGER CHECK (protein_hit IN (0, 1)),
    gassed          INTEGER CHECK (gassed IN (0, 1)),
    niggles         TEXT,
    day_note        TEXT,
    social_meal     INTEGER CHECK (social_meal IN (0, 1)),
    sleep_quality   INTEGER CHECK (sleep_quality BETWEEN 1 AND 10),
    stress          INTEGER CHECK (stress BETWEEN 1 AND 10),
    fatigue         INTEGER CHECK (fatigue BETWEEN 1 AND 10),
    muscle_soreness INTEGER CHECK (muscle_soreness BETWEEN 1 AND 10),
    hooper_index    INTEGER,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Tape measurements. One row per (date, measurement_type) so it's not locked to waist
-- alone. Baseline waist is 86 cm (config/athlete.yaml), measured Sunday, fasted, below
-- navel.
CREATE TABLE IF NOT EXISTS body_measurements (
    date             TEXT NOT NULL,
    measurement_type TEXT NOT NULL DEFAULT 'waist',
    value_cm         REAL NOT NULL,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (date, measurement_type)
);

-- Every computed metric from the kickoff doc's "Derived metrics" section (HRV
-- baseline, ACWR, monotony/strain, sleep debt, weight trend, comp countdown,
-- readiness score + components, ...). Long/tidy format — one row per (date,
-- metric_name) — so every metric self-documents the inputs and window size that
-- produced it (design principle 9), without a wide table growing a column per metric
-- across every future phase.
CREATE TABLE IF NOT EXISTS derived_daily (
    date         TEXT NOT NULL,
    metric_name  TEXT NOT NULL,                -- e.g. "hrv_baseline_status", "acwr", "readiness_score"
    value        REAL,
    unit         TEXT,
    window_days  INTEGER,
    n_days       INTEGER,                      -- actual data points behind this value
    confidence   TEXT,                         -- e.g. "insufficient_data" | "provisional" | "full"
    inputs_json  TEXT,                         -- JSON blob: the inputs/intermediate arithmetic behind `value`
    computed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (date, metric_name)
);

-- Audit log for every ingestion run, any source. Read by the "Data health" dashboard
-- page (kickoff doc section 8) — this is how a silently-broken pipeline gets noticed.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed')),
    rows_in       INTEGER,
    rows_upserted INTEGER,
    rows_skipped  INTEGER,
    errors        TEXT                         -- JSON array of error messages, if any
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_source ON ingest_runs (source, started_at);
