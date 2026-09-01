"""Cross-source deduplication for `activities` (design principle 5, Phase 3).

Full precedence is Garmin > Strava > Apple Health. All three sources are loaded
as of 2026-08-28 — Garmin's arrival needed zero changes here, exactly as
designed: any Garmin row matching an existing Strava/Apple-Health winner just
out-ranks it on the same precedence list and takes over on the next
`dedupe_activities()` run. In practice, adding Garmin's 139 historical
activities didn't trigger any *new* merges beyond the 5 already found between
Strava/Apple Health — checked, not assumed; see CLAUDE.md's Garmin backfill
summary for why (mostly auto-detected walking activities whose start/duration
don't line up closely enough to clear the matching bar below).

Matching (design principle 5): start time within 120s, duration within 60s, and
"same sport family" — a small compatibility table below, since Strava's and Apple
HealthKit's sport vocabularies don't line up 1:1 (e.g. Strava's generic "workout"
vs Apple's "functional_strength_training" — confirmed as the same real session in
Francisco's actual data, 2026-08-27: 5 activities matched exactly on start time
and duration under these two labels). Sport-family compatibility is a secondary
signal here, not the primary one — start-time-and-duration match this tight is
already an extremely strong signal on its own that two rows are the same event.

Merging deletes the loser row(s) and records them in the winner's `merged_from`
JSON (design principle 5: "log every merge decision to a table I can audit" —
`merged_from` on the surviving row *is* that audit trail, not a separate table).
This is safe to delete rather than just hide, because dedup is meant to run as
its own step after ingestion (mirrors the planned `scripts/sync.py`: sync, then
recompute) — if a source gets re-ingested later and resurrects a merged-away row,
the next dedup pass just merges it away again. Never run dedup logic inside the
per-source upsert loop itself.

**Second matching tier added 2026-08-30, a real gap found while investigating
why bike rides don't show up on the Training page**: 8 real Strava/Garmin ride
pairs in Francisco's actual account (May-Aug 2026, both auto-uploads of the
same physical Garmin-recorded ride) never merged under the primary rule — start
times differ by exactly 7200s (2 hours, confirmed a real cross-source
discrepancy, not an ingestion bug: Strava's raw CSV genuinely states the local
wall-clock time 2 hours earlier than Garmin's own `startTimeLocal`/`startTimeGMT`
pair for the identical ride, verified directly against both the raw CSV and a
live Garmin API call), and duration sometimes differs by much more than 60s too
(Strava's `Elapsed Time` vs. whatever duration convention Garmin's live-sync
endpoint uses). What's nearly identical across every single pair, confirmed
directly: `avg_hr`, within a rounding difference of at most 1bpm (one real pair,
2026-08-15, was 153 vs. 152 — presumably each platform rounding its own slightly
different sample set the same real ride). So a second, narrower rule now
matches on same local date + same sport family + `avg_hr` within
`AVG_HR_TOLERANCE` + a start-time offset close to that documented exactly-2-hour
discrepancy (`SECONDARY_TIME_OFFSET_TARGET_S` +- `SECONDARY_TIME_OFFSET_TOLERANCE_S`),
even when the primary start/duration check fails. First built with exact-equality
only; widened to +-1bpm the same day after this exact 2026-08-15 pair was found
still unmerged and visibly double-counting that day's training load on the
Training page.

**Narrowed 2026-08-31, a real false-positive found in review**: the original
version of this tier used a blanket 0-6 hour start-time window with no other
corroborating signal, on the theory that a same-day, same-sport-family,
near-exact `avg_hr` match was already discriminating enough on its own. It
wasn't — reproduced directly: two genuinely distinct real rides ~5 hours apart,
both sitting at a similar Z2 heart rate (~140bpm, a realistic scenario for this
athlete's prescribed rides, see `config/athlete.yaml: comp_prep`'s Saturday Z2
sessions), landed inside that 6-hour window and got silently merged, deleting
one of two real training sessions. The tier only actually needs to catch start
times a fixed ~2 hours apart (the one specific, confirmed real discrepancy
above) — not "anywhere in a 6-hour span" — so the window is now a narrow band
centered on that exact offset instead of a blanket bound from zero.

**Real gap in `_SPORT_FAMILIES` found the same day, same investigation**: a
2026-08-24 Strava "weight_training" + Garmin "strength_training" pair (same
physical gym session — avg_hr 116 on both, duration within 1s, the same
2-hour cross-source timestamp pattern above) never even reached either
matching tier, because `strength_training` had no family mapping at all and
so counted as its own, unmatched family. Added, along with a few other real
Garmin-specific labels found the same way (`trail_running`/
`treadmill_running` -> running, `lap_swimming` -> swimming) that were
previously unmapped for the same underlying reason.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from health_os.core.timezones import parse_utc

DEFAULT_PRECEDENCE = ("garmin", "strava", "apple_health")
START_TOLERANCE_S = 120
DURATION_TOLERANCE_S = 60

# Secondary tier (see module docstring): a narrow band centered on the one
# documented, confirmed-real discrepancy (Strava vs. Garmin local time off by
# exactly 2 hours for the same physical ride) -- NOT a blanket window from
# zero. A blanket 0-6h window was tried first and produced a real false
# positive (two distinct real rides ~5 hours apart, similar avg_hr, silently
# merged) -- narrowed 2026-08-31 once that was reproduced. The tolerance
# around the exact 2h offset is deliberately small: just enough slack for
# rounding/logging jitter, not a second wide window in disguise.
SECONDARY_TIME_OFFSET_TARGET_S = 2 * 3600
SECONDARY_TIME_OFFSET_TOLERANCE_S = 5 * 60

# +-1bpm, not exact equality -- a real pair (2026-08-15, 153 vs. 152) showed
# each platform can round its own computed average slightly differently for
# the identical physical ride. Still an extremely tight bound combined with
# the same-date + same-sport-family gate above.
AVG_HR_TOLERANCE = 1

# Sport-family compatibility for matching, not a canonicalization of `sport`
# itself (that column keeps each source's own normalized label). Unmapped sports
# are their own family — conservative by default, so an unfamiliar sport string
# never accidentally matches something else. Folding Strava's catch-all "workout"
# into "strength" is deliberately permissive: it's only ever consulted as a
# tie-breaker alongside an already-tight start-time/duration match, never alone.
_SPORT_FAMILIES = {
    "ride": "cycling",
    "cycling": "cycling",
    "run": "running",
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "running",
    "walk": "walking",
    "walking": "walking",
    "hike": "hiking",
    "hiking": "hiking",
    "swim": "swimming",
    "swimming": "swimming",
    "lap_swimming": "swimming",
    "yoga": "yoga",
    "weight_training": "strength",
    "strength_training": "strength",
    "traditional_strength_training": "strength",
    "functional_strength_training": "strength",
    "workout": "strength",
    "rock_climb": "climbing",
    "climbing": "climbing",
    "martial_arts": "martial_arts",
    "wrestling": "martial_arts",
    "high_intensity_interval_training": "hiit",
}


def _sport_family(sport: str | None) -> str:
    if not sport:
        return "unknown"
    return _SPORT_FAMILIES.get(sport, sport)


@dataclass(slots=True)
class _Row:
    activity_id: str
    source: str
    source_id: str
    local_date: str
    start_utc: str
    duration_s: int | None
    sport: str | None
    avg_hr: float | None
    merged_from: list[dict[str, str]]


def _load_rows(conn: sqlite3.Connection) -> list[_Row]:
    rows = conn.execute(
        "SELECT activity_id, source, source_id, local_date, start_utc, "
        "duration_s, sport, avg_hr, merged_from FROM activities"
    ).fetchall()
    result = []
    for r in rows:
        merged = json.loads(r["merged_from"]) if r["merged_from"] else []
        result.append(
            _Row(
                activity_id=r["activity_id"],
                source=r["source"],
                source_id=r["source_id"],
                local_date=r["local_date"],
                start_utc=r["start_utc"],
                duration_s=r["duration_s"],
                sport=r["sport"],
                avg_hr=r["avg_hr"],
                merged_from=merged,
            )
        )
    return result


def _is_match(a: _Row, b: _Row) -> bool:
    if a.local_date != b.local_date or a.source == b.source:
        return False
    if _sport_family(a.sport) != _sport_family(b.sport):
        return False

    start_diff = abs((parse_utc(a.start_utc) - parse_utc(b.start_utc)).total_seconds())
    dur_diff = abs((a.duration_s or 0) - (b.duration_s or 0))
    if start_diff <= START_TOLERANCE_S and dur_diff <= DURATION_TOLERANCE_S:
        return True

    # Secondary tier (module docstring): a near-exact avg_hr match PLUS a
    # start-time offset close to the one documented, confirmed-real 2-hour
    # Strava/Garmin discrepancy -- not just "any near-exact avg_hr match,"
    # which a real false positive (two distinct rides ~5 hours apart, similar
    # avg_hr) showed isn't discriminating enough on its own.
    return (
        a.avg_hr is not None
        and b.avg_hr is not None
        and abs(a.avg_hr - b.avg_hr) <= AVG_HR_TOLERANCE
        and abs(start_diff - SECONDARY_TIME_OFFSET_TARGET_S) <= SECONDARY_TIME_OFFSET_TOLERANCE_S
    )


def _find(parent: dict[str, str], x: str) -> str:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: dict[str, str], x: str, y: str) -> None:
    root_x, root_y = _find(parent, x), _find(parent, y)
    if root_x != root_y:
        parent[root_x] = root_y


def _cluster(rows: list[_Row]) -> list[list[_Row]]:
    """Group rows into duplicate clusters via union-find over pairwise matches,
    scoped per local_date (the only rows that could ever match) to keep this
    trivially cheap at personal-database scale.
    """
    by_date: dict[str, list[_Row]] = {}
    for row in rows:
        by_date.setdefault(row.local_date, []).append(row)

    clusters: list[list[_Row]] = []
    for day_rows in by_date.values():
        parent = {r.activity_id: r.activity_id for r in day_rows}

        for i, a in enumerate(day_rows):
            for b in day_rows[i + 1 :]:
                if _is_match(a, b):
                    _union(parent, a.activity_id, b.activity_id)

        groups: dict[str, list[_Row]] = {}
        for r in day_rows:
            groups.setdefault(_find(parent, r.activity_id), []).append(r)
        clusters.extend(g for g in groups.values() if len(g) > 1)

    return clusters


def _pick_winner(cluster: list[_Row], precedence: tuple[str, ...]) -> tuple[_Row, list[_Row]]:
    def rank(row: _Row) -> int:
        return precedence.index(row.source) if row.source in precedence else len(precedence)

    ordered = sorted(cluster, key=rank)
    return ordered[0], ordered[1:]


def _dedupe_merged_from(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    """De-dupe (source, source_id) pairs, preserving first-seen order.

    Needed because a source can be re-ingested after its row was already merged
    away (e.g. re-running `scripts/backfill.py` re-parses the export and
    resurrects the row — expected, see module docstring), and the next dedupe
    pass then re-absorbs it. Without this, the same superseded row would pile up
    duplicate entries in `merged_from` every time the pipeline re-runs, which
    is misleading for an audit trail even though it isn't factually wrong.
    """
    seen: set[tuple[str, str]] = set()
    result = []
    for entry in entries:
        key = (entry["source"], entry["source_id"])
        if key not in seen:
            seen.add(key)
            result.append(entry)
    return result


@dataclass(slots=True)
class DedupeResult:
    groups_merged: int
    rows_deleted: int
    winners: list[str]  # activity_ids that absorbed at least one duplicate
    fk_conflicts: list[str]  # loser activity_ids that could NOT be deleted (see below)


def dedupe_activities(
    conn: sqlite3.Connection, precedence: tuple[str, ...] = DEFAULT_PRECEDENCE
) -> DedupeResult:
    """Find and merge cross-source duplicate activities. Idempotent — running
    this twice with no new ingestion in between finds nothing the second time,
    since the loser rows are gone after the first pass.

    A loser row can be referenced by `bjj_sessions.linked_activity_id` or
    `activity_laps.activity_id` (neither FK declares `ON DELETE CASCADE`), so
    deleting it would violate a foreign key with `PRAGMA foreign_keys = ON`.
    Not reachable via the two real call sites today (default precedence always
    ranks Garmin highest, and laps only ever attach to Garmin rows) — but
    latent, and a bare `DELETE` here would otherwise raise mid-loop and abort
    every cluster in the same pass, including ones already merged, with no
    `ingest_runs` record of any of it (this function isn't itself wrapped in
    start/finish_ingest_run). Each loser's delete is caught individually
    instead: a conflicting loser is skipped (left unmerged, NOT recorded as
    absorbed) rather than crashing the rest of the run, and its id is
    collected in `fk_conflicts` — never silently dropped, design principle 6.
    """
    rows = _load_rows(conn)
    clusters = _cluster(rows)

    winners: list[str] = []
    rows_deleted = 0
    fk_conflicts: list[str] = []
    with conn:
        for cluster in clusters:
            winner, losers = _pick_winner(cluster, precedence)
            new_merged = list(winner.merged_from)
            for loser in losers:
                try:
                    conn.execute(
                        "DELETE FROM activities WHERE activity_id = ?", (loser.activity_id,)
                    )
                except sqlite3.IntegrityError:
                    fk_conflicts.append(loser.activity_id)
                    continue
                # Record the loser's own identity, plus anything IT had already
                # absorbed in an earlier merge pass (transitive: e.g. Garmin
                # later out-ranking a row that already absorbed an Apple Health
                # duplicate before Garmin was loaded). Only recorded once the
                # delete above actually succeeded.
                new_merged.append({"source": loser.source, "source_id": loser.source_id})
                new_merged.extend(loser.merged_from)
                rows_deleted += 1
            new_merged = _dedupe_merged_from(new_merged)
            conn.execute(
                "UPDATE activities SET merged_from = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE activity_id = ?",
                (json.dumps(new_merged), winner.activity_id),
            )
            winners.append(winner.activity_id)

    return DedupeResult(
        groups_merged=len(clusters),
        rows_deleted=rows_deleted,
        winners=winners,
        fk_conflicts=fk_conflicts,
    )
