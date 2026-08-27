"""Cross-source deduplication for `activities` (design principle 5, Phase 3).

Full precedence is Garmin > Strava > Apple Health, but this is written to work
correctly with however many of those three sources are actually loaded — right
now that's just Strava and Apple Health (Garmin's backfill hasn't landed yet).
Adding Garmin later needs no changes here, just re-running `dedupe_activities()`
after its ingestion: any Garmin row that matches an existing Strava/Apple-Health
winner will out-rank it on the same precedence list and take over.

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
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from health_os.core.timezones import parse_utc

DEFAULT_PRECEDENCE = ("garmin", "strava", "apple_health")
START_TOLERANCE_S = 120
DURATION_TOLERANCE_S = 60

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
    "walk": "walking",
    "walking": "walking",
    "hike": "hiking",
    "hiking": "hiking",
    "swim": "swimming",
    "swimming": "swimming",
    "yoga": "yoga",
    "weight_training": "strength",
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
    merged_from: list[dict[str, str]]


def _load_rows(conn: sqlite3.Connection) -> list[_Row]:
    rows = conn.execute(
        "SELECT activity_id, source, source_id, local_date, start_utc, "
        "duration_s, sport, merged_from FROM activities"
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
                merged_from=merged,
            )
        )
    return result


def _is_match(a: _Row, b: _Row) -> bool:
    if a.local_date != b.local_date or a.source == b.source:
        return False
    start_diff = abs((parse_utc(a.start_utc) - parse_utc(b.start_utc)).total_seconds())
    if start_diff > START_TOLERANCE_S:
        return False
    dur_diff = abs((a.duration_s or 0) - (b.duration_s or 0))
    if dur_diff > DURATION_TOLERANCE_S:
        return False
    return _sport_family(a.sport) == _sport_family(b.sport)


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


def dedupe_activities(
    conn: sqlite3.Connection, precedence: tuple[str, ...] = DEFAULT_PRECEDENCE
) -> DedupeResult:
    """Find and merge cross-source duplicate activities. Idempotent — running
    this twice with no new ingestion in between finds nothing the second time,
    since the loser rows are gone after the first pass.
    """
    rows = _load_rows(conn)
    clusters = _cluster(rows)

    winners: list[str] = []
    rows_deleted = 0
    with conn:
        for cluster in clusters:
            winner, losers = _pick_winner(cluster, precedence)
            new_merged = list(winner.merged_from)
            for loser in losers:
                # Record the loser's own identity, plus anything IT had already
                # absorbed in an earlier merge pass (transitive: e.g. Garmin
                # later out-ranking a row that already absorbed an Apple Health
                # duplicate before Garmin was loaded).
                new_merged.append({"source": loser.source, "source_id": loser.source_id})
                new_merged.extend(loser.merged_from)
                conn.execute("DELETE FROM activities WHERE activity_id = ?", (loser.activity_id,))
                rows_deleted += 1
            new_merged = _dedupe_merged_from(new_merged)
            conn.execute(
                "UPDATE activities SET merged_from = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE activity_id = ?",
                (json.dumps(new_merged), winner.activity_id),
            )
            winners.append(winner.activity_id)

    return DedupeResult(groups_merged=len(clusters), rows_deleted=rows_deleted, winners=winners)
