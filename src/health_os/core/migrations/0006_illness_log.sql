-- Migration 0006: illness log.
--
-- Francisco asked directly (2026-09-04, feeling under the weather -- sore
-- throat, feeling weak/feverish without a measured fever, slight congestion,
-- after a day of heavy allergies + an antihistamine) to track every illness
-- episode with whatever info he gives, so that once enough episodes
-- accumulate, illness can eventually be correlated against HRV/RHR/sleep/
-- training-load the same way metrics/correlations.py already does for other
-- pairs (see that module for the honesty gates -- MIN_N=30 real paired
-- observations, Bonferroni-corrected -- illness isn't wired into it yet,
-- deliberately: episodes are hopefully rare, and it would misrepresent the
-- data to test a pair before it has anywhere near enough).
--
-- One row per DATE, not one row per "episode" -- same grain as
-- subjective_log/body_measurements. Episode boundaries are a derived/
-- interpretive concept (design principle 6: raw vs. derived stays separate),
-- not raw data -- a run of consecutive dated entries naturally represents an
-- episode without needing an explicit start/end field to get out of sync
-- with the day-by-day reality.
--
-- Every field except `date` is nullable, and deliberately never defaulted to
-- 0/False -- this logger will very often be used with partial info (e.g. no
-- thermometer available, or a symptom simply not mentioned that day), and a
-- field Francisco didn't mention must stay NULL, never invented (design
-- principle 6). `severity` uses the SAME polarity as subjective_log's 1-10
-- fields (1 = best/barely noticeable, 10 = worst/severe) for consistency.
-- `fever` is self-assessed ("do you feel feverish") and deliberately
-- distinct from `temperature_c` (an actual measured value, only present when
-- a thermometer was used) -- conflating the two would silently upgrade a
-- felt sensation into a confirmed reading.
CREATE TABLE IF NOT EXISTS illness_log (
    date             TEXT PRIMARY KEY,
    severity         INTEGER CHECK (severity BETWEEN 1 AND 10),
    sore_throat      INTEGER,
    fever            INTEGER,
    temperature_c    REAL,
    congestion       INTEGER,
    cough            INTEGER,
    body_aches       INTEGER,
    fatigue_weakness INTEGER,
    headache         INTEGER,
    likely_cause     TEXT,
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
