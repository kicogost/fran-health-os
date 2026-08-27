-- Migration 0002: BJJ session detail + daily wellness questionnaire.
--
-- bjj_sessions: replaces the boolean `gassed` with `rounds_gassed` (a count is
-- strictly more informative than a bool — gassed=true tells you nothing about
-- whether that was 1 round of 8 or 6 of 8) and adds `session_feeling`, an
-- end-of-session physical-state check specifically distinguishing ordinary hard
-- fatigue from something more concerning ("dizzy") — a real safety signal given
-- the athlete's injury history and the project's existing safety-rail design.
-- Both tables were empty in production at migration time (verified 2026-08-27),
-- so this is a clean cutover, not a data migration.
--
-- subjective_log: adds a Hooper-Mackinnon-inspired daily wellness questionnaire
-- (sleep quality, stress, fatigue, muscle soreness — see docs/decisions and
-- CLAUDE.md for the research this is based on). All four use the SAME polarity
-- (1 = best, 10 = worst) specifically so they sum cleanly into `hooper_index`
-- (4 = excellent wellness, 40 = terrible) without needing to remember which
-- fields invert. `hooper_index` is computed by core.models.SubjectiveLogEntry,
-- same pattern as bjj_sessions.computed_load — never entered by hand.

ALTER TABLE bjj_sessions DROP COLUMN gassed;

ALTER TABLE bjj_sessions ADD COLUMN rounds_gassed INTEGER;

ALTER TABLE bjj_sessions ADD COLUMN session_feeling TEXT
    CHECK (session_feeling IN ('dizzy', 'gassed', 'tired', 'okay'));
    -- worst -> best: dizzy (concerning, not just hard training), gassed,
    -- tired (normal hard-session fatigue), okay (fresh)

ALTER TABLE subjective_log ADD COLUMN sleep_quality INTEGER CHECK (sleep_quality BETWEEN 1 AND 10);
ALTER TABLE subjective_log ADD COLUMN stress INTEGER CHECK (stress BETWEEN 1 AND 10);
ALTER TABLE subjective_log ADD COLUMN fatigue INTEGER CHECK (fatigue BETWEEN 1 AND 10);
ALTER TABLE subjective_log ADD COLUMN muscle_soreness INTEGER CHECK (muscle_soreness BETWEEN 1 AND 10);
ALTER TABLE subjective_log ADD COLUMN hooper_index INTEGER; -- sum of the 4 above, when all present
