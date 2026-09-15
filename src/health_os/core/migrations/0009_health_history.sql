-- Migration 0009: general health history — bloodwork, medical events,
-- medications/supplements, allergies, family medical history.
--
-- Francisco asked directly (2026-09-14) to make this his general health
-- dashboard, not just a fitness/BJJ tracker — CLAUDE.md's own opening line
-- already calls this a "health data warehouse," so this is a natural
-- extension of scope, not a departure. He chose 4 categories directly, split
-- here into 5 tables because bloodwork and medications/allergies each have a
-- genuinely different grain from one another (see per-table notes below).
--
-- All 5 tables follow this project's established conventions: nullable-
-- except-natural-key fields (design principle 6 — never invent/interpolate a
-- value that wasn't actually given), the same `created_at`/`updated_at`
-- DEFAULT timestamp pattern used everywhere else, and CHECK constraints only
-- on genuinely bounded/enumerable fields (free-text fields like `test_name`
-- or `condition` are deliberately left unconstrained — the real set of
-- possible lab tests or conditions is open-ended, an enum would be wrong).
--
-- Natural-key note, deliberately asymmetric across these 5 tables: bloodwork
-- results, medical events, and medications/supplements have NO natural key
-- to upsert on — design principle 2 (raw data is immutable) reads most
-- literally here as "log a fresh record every time," not "correct a prior
-- one in place." A second blood draw, a follow-up diagnosis note, or
-- restarting a medication are all genuinely NEW rows, not corrections to an
-- old one — autoincrement `id` is the only key. Allergies and family history
-- are the opposite: an allergen or a (relation, condition) pair really is a
-- single, correctable fact ("mild -> severe" is an update to what's known
-- about the SAME allergy, not a second allergy), so those two get a real
-- natural key and are upserted, same as every daily logger elsewhere in this
-- project.

-- One row per (draw date, single test value) — a real "long/tall" table, not
-- one column per possible lab test. The set of possible tests (ferritin,
-- testosterone, vitamin D, LDL cholesterol, ...) is unbounded, so `test_name`
-- is free text, not an enum — a wide table would need a schema migration
-- every time a new test type showed up, exactly the kind of design mistake
-- this project's own conventions avoid elsewhere (see e.g. calisthenics'
-- exercises_json for the same "the set of things is open-ended" reasoning).
-- `unit` is stored alongside every value, never assumed — units genuinely
-- vary by test AND by lab (ng/mL vs nmol/L for the same hormone is a real,
-- common difference). `reference_range_low`/`high` are what the lab itself
-- reports next to the result and matter for interpretation, but aren't
-- always available (older/scanned reports, some point-of-care tests) — both
-- nullable, and independently nullable from each other (a range can be
-- one-sided, e.g. "< 5.0 ng/mL" has no meaningful low bound).
-- No natural key: see migration header note above. A real duplicate (the same
-- test re-entered by mistake) is a data-entry problem to fix by deleting the
-- wrong row directly, not something a UNIQUE constraint should silently
-- prevent or silently overwrite.
CREATE TABLE IF NOT EXISTS bloodwork_results (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    date                 TEXT NOT NULL,
    test_name            TEXT NOT NULL,
    value                REAL NOT NULL,
    unit                 TEXT,
    reference_range_low  REAL,
    reference_range_high REAL,
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_bloodwork_results_test_name ON bloodwork_results (test_name);
CREATE INDEX IF NOT EXISTS idx_bloodwork_results_date ON bloodwork_results (date);

-- A real chronological timeline: conditions, diagnoses, injuries, surgeries,
-- hospitalizations — one table, differentiated by `category`, not five
-- separate tables, since they all share the same real shape (a start date,
-- an optional resolution, a description). Francisco's own permanent knee
-- injury and recurring neck sensitivity (both already referenced as real,
-- ongoing conditions in config/athlete.yaml's injury guardrails) are exactly
-- the kind of `status='ongoing'` row this table exists to hold. No natural
-- key, autoincrement `id` only: unlike the daily-logger tables, multiple real
-- events can plausibly share a date (e.g. a diagnosis and an injury on the
-- same visit), so this deliberately isn't a "one entry per day" table.
-- `resolved_date` is only meaningful once `status='resolved'` — enforced in
-- Python (core.models.MedicalEvent.__post_init__), matching this project's
-- existing convention of validating cross-field relationships in the
-- dataclass rather than as a SQL CHECK (e.g. BjjSession's
-- rounds_gassed <= rounds_rolled), reserving CHECK constraints here for the
-- genuinely single-field bounded domains (`category`, `status`).
CREATE TABLE IF NOT EXISTS medical_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (
                       category IN ('condition', 'injury', 'surgery', 'hospitalization', 'other')
                   ),
    title          TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('ongoing', 'resolved', 'unknown')),
    resolved_date  TEXT,
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_medical_events_date ON medical_events (date);

-- One row per COURSE of taking something, not one row per medication name —
-- the same medication can plausibly be started, stopped, and restarted
-- later (a real, separate course each time), so autoincrement `id` is the
-- only key, no natural key to upsert on (same reasoning as bloodwork/
-- medical_events above). `end_date IS NULL` means "currently taking it" —
-- a real, meaningful NULL (design principle 6), not "unknown," so it's never
-- defaulted to today's date on entry. `dosage`/`frequency` are free text
-- ("500mg" / "2 capsules", "daily" / "as needed") rather than normalized
-- numeric+unit columns — real-world dosage units vary too much (mg, IU,
-- capsules, drops, mL...) to force into one schema without either losing
-- information or needing a unit-conversion table this project has no use
-- for elsewhere.
CREATE TABLE IF NOT EXISTS medications_supplements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('medication', 'supplement')),
    dosage      TEXT,
    frequency   TEXT,
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_medications_supplements_name ON medications_supplements (name);

-- A simpler, mostly-static list — genuinely one row per real-world allergen,
-- so `allergen` IS the natural key (same "single-column TEXT PRIMARY KEY"
-- pattern as daily_metrics.date/subjective_log.date), unlike the three
-- always-insert tables above. Re-logging the same allergen (e.g. updating
-- `severity` once it's better characterized) is a real UPDATE to the same
-- fact, not a new allergy — upserted, with the CLI/API warning before
-- overwriting, same as every other natural-keyed logger in this project.
-- `severity` is nullable (not every allergy has a known/reported severity);
-- `date_identified` is nullable too — often genuinely unknown (e.g. "always
-- had this").
CREATE TABLE IF NOT EXISTS allergies (
    allergen         TEXT PRIMARY KEY,
    reaction         TEXT,
    severity         TEXT CHECK (severity IN ('mild', 'moderate', 'severe')),
    date_identified  TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- `relation` (e.g. "mother", "paternal grandfather") is free text, not an
-- enum — real family structures don't fit a fixed small list cleanly.
-- UNIQUE(relation, condition) makes re-logging the same fact idempotent
-- (upsert, warn before overwrite) rather than silently accumulating
-- duplicate rows for "mother — hypertension" logged twice.
CREATE TABLE IF NOT EXISTS family_medical_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    relation    TEXT NOT NULL,
    condition   TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (relation, condition)
);
